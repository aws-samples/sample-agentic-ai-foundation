#!/usr/bin/env python3
"""
Simple evaluation: run tests, get recent traces, evaluate
"""

import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from langfuse import Langfuse

def run_test_queries(agent_url=None):
    """Run test queries from groundtruth through the agent"""
    if agent_url is None:
        agent_url = os.getenv("AGENT_ARN", "http://localhost:8080")
    
    groundtruth = create_groundtruth()
    queries = [gt['query'] for gt in groundtruth]
    
    results = []
    print("Running test queries...")
    groundtruth_size = len(groundtruth)
    for i, query in enumerate(queries):
        print(f"{i+1}/{groundtruth_size}: {query}")
        
        try:
            response = requests.post(
                f"{agent_url}/invocations",
                json={"input": {"prompt": query}},
                timeout=30
            )
            
            results.append({
                "query": query,
                "success": response.status_code == 200,
                "response": response.json() if response.status_code == 200 else None
            })
            
        except Exception as e:
            results.append({
                "query": query, 
                "success": False,
                "error": str(e)
            })
        
        time.sleep(2)
    
    return results

def get_recent_traces(langfuse, minutes=10):
    """Get all traces from the last N minutes"""
    from datetime import timezone
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    
    traces = langfuse.api.trace.list(limit=100)
    recent_traces = []
    
    for trace in traces.data:
        if hasattr(trace, 'timestamp') and trace.timestamp:
            # Handle both timezone-aware and naive timestamps
            trace_time = trace.timestamp
            if trace_time.tzinfo is None:
                trace_time = trace_time.replace(tzinfo=timezone.utc)
            if trace_time >= cutoff:
                recent_traces.append(trace.id)
    
    print(f"Found {len(recent_traces)} traces from last {minutes} minutes")
    return recent_traces

def extract_detailed_metrics(langfuse, trace_ids):
    """Extract detailed metrics from traces"""
    import json
    
    all_results = []
    
    for trace_id in trace_ids:
        try:
            observations = langfuse.api.observations.get_many(trace_id=trace_id)
            df_observation = pd.DataFrame([obs.dict() for obs in observations.data])
            
            if df_observation.empty:
                continue
                
            # Filter for LangGraph and TOOL observations
            filtered_observations = df_observation[
                (df_observation['name'] == 'LangGraph') | 
                (df_observation['type'] == 'TOOL')
            ]
            
            for idx, row in filtered_observations.iterrows():
                if 'output' in row and row['output']:
                    observation_data = row['output']
                    observation_data['csv_rows'] = df_observation.to_dict('records')
                    
                    metrics = extract_tool_metrics(observation_data)
                    
                    if metrics['tool_calls']:  # Only include if has tool calls
                        metrics.update({
                            'trace_id': trace_id,
                            'observation_id': row.get('id', idx),
                            'observation_type': row.get('type'),
                            'observation_name': row.get('name'),
                            'observation_latency': row.get('latency', 0)
                        })
                        all_results.append(metrics)
                        
        except Exception as e:
            continue
    
    return pd.DataFrame(all_results)

def extract_tool_metrics(observation_data):
    """Extract comprehensive tool metrics from observation data"""
    import json
    
    messages = observation_data.get('messages', [])
    
    tool_calls = []
    tool_responses = {}
    tool_sequence = []
    tool_calls_with_params = []
    user_query = None
    final_response = None
    tool_latencies = []
    
    for msg in messages:
        if msg['type'] == 'human':
            user_query = msg['content']
        elif msg['type'] == 'ai' and not msg.get('tool_calls'):
            final_response = msg['content']
        elif msg['type'] == 'ai' and msg.get('tool_calls'):
            for tool_call in msg['tool_calls']:
                tool_name = tool_call['name']
                tool_args = tool_call['args']
                
                tool_calls.append(tool_name)
                tool_sequence.append(tool_name)
                tool_calls_with_params.append({
                    'tool': tool_name,
                    'parameters': tool_args
                })
        elif msg['type'] == 'tool':
            tool_responses[msg['tool_call_id']] = {
                'name': msg['name'],
                'status': msg.get('status', 'unknown'),
                'content': msg['content']
            }
    
    # Extract latencies from CSV data
    for row in observation_data.get('csv_rows', []):
        if row.get('type') == 'TOOL' and row.get('latency'):
            tool_latencies.append({
                'tool_name': row.get('name'),
                'latency_ms': row.get('latency')
            })
    
    success_rate = sum(1 for resp in tool_responses.values() if resp['status'] == 'success') / len(tool_responses) if tool_responses else 0
    
    retrieval_scores = []
    response_times = []
    
    for resp in tool_responses.values():
        try:
            content = json.loads(resp['content'])
            if 'retrieved_documents' in content:
                scores = [doc['relevance_score'] for doc in content['retrieved_documents']]
                retrieval_scores.extend(scores)
            if 'response_time' in content:
                response_times.append(content['response_time'])
        except (json.JSONDecodeError, KeyError):
            continue
    
    return {
        'user_query': user_query,
        'final_response': final_response,
        'tool_calls': tool_calls,
        'tool_calls_with_params': tool_calls_with_params,
        'tool_latencies': tool_latencies,
        'success_rate': success_rate,
        'tool_sequence': tool_sequence,
        'retrieval_scores': retrieval_scores,
        'response_times': response_times,
        'total_tools_used': len(tool_calls),
        'successful_tools': sum(1 for resp in tool_responses.values() if resp['status'] == 'success')
    }

def create_groundtruth():
    """Create groundtruth for the 10 test queries"""
    return [
        {"query": "How do I reset my router hub?", "expected_tools": ["retrieve_context", "web_search"]},
        {"query": "What is Pelican App?", "expected_tools": ["retrieve_context"]},
        {"query": "What's the ANYCOMPANYPower Save feature and how do I set it up to turn off wireless at night", "expected_tools": ["retrieve_context", "web_search"]},
        {"query": "can you tell me what the weather is in LA?", "expected_tools": ["web_search"]},
        {"query": "Create a support ticket for me for my router problem?", "expected_tools": ["retrieve_context", "create_support_ticket"]},
        {"query": "My device won't turn on", "expected_tools": ["retrieve_context", "web_search"]}
    ]

def evaluate_against_groundtruth(metrics_df, groundtruth):
    """Compare metrics with groundtruth expectations"""
    evaluation_results = []
    
    for gt in groundtruth:
        query = gt['query']
        expected_tools = set(gt['expected_tools'])
        
        # Find matching metrics
        matches = metrics_df[metrics_df['user_query'].str.contains(query[:20], na=False)]
        
        if matches.empty:
            evaluation_results.append({
                'query': query,
                'expected_tools': list(expected_tools),
                'actual_tools': [],
                'precision': 0.0,
                'recall': 0.0,
                'f1': 0.0,
                'found_trace': False
            })
        else:
            actual_tools = set(matches.iloc[0]['tool_calls'])
            
            tp = len(expected_tools & actual_tools)
            fp = len(actual_tools - expected_tools)
            fn = len(expected_tools - actual_tools)
            
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
            
            evaluation_results.append({
                'query': query,
                'expected_tools': list(expected_tools),
                'actual_tools': list(actual_tools),
                'precision': precision,
                'recall': recall,
                'f1': f1,
                'found_trace': True
            })
    


def main():
    """Main evaluation function"""
    # Initialize Langfuse
    langfuse = Langfuse(
        host=os.getenv("LANGFUSE_HOST"),
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY")
    )
    
    print("Starting simple evaluation...")
    
    # Run test queries
    test_results = run_test_queries()
    test_df = pd.DataFrame(test_results)
    test_df.to_csv('test_results.csv', index=False)
    print(f"Completed {len(test_results)} test queries")
    
    # Wait for traces to be processed
    print("Waiting for traces to be processed...")
    time.sleep(30)
    
    # Get recent traces
    trace_ids = get_recent_traces(langfuse, minutes=15)
    
    if not trace_ids:
        print("No recent traces found")
        return
    
    # Extract metrics
    metrics_df = extract_detailed_metrics(langfuse, trace_ids)
    metrics_df.to_csv('trace_metrics.csv', index=False)
    print(f"Extracted metrics from {len(metrics_df)} traces")
    
    # Evaluate against groundtruth
    groundtruth = create_groundtruth()
    evaluation_df = evaluate_against_groundtruth(metrics_df, groundtruth)
    evaluation_df.to_csv('evaluation_results.csv', index=False)
    
    # Generate summary report
    report = {
        'timestamp': datetime.now().isoformat(),
        'total_queries': len(test_results),
        'successful_queries': sum(1 for r in test_results if r['success']),
        'traces_found': len(trace_ids),
        'avg_f1_score': evaluation_df['f1'].mean(),
        'queries_with_traces': evaluation_df['found_trace'].sum()
    }
    
    import json
    with open('performance_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"Evaluation complete. Average F1 score: {report['avg_f1_score']:.3f}")

if __name__ == "__main__":
    main()rn pd.DataFrame(evaluation_results)

def generate_performance_report(metrics_df, retrieval_threshold=0.5, latency_threshold=2000, total_latency_threshold=5000):
    """Generate performance report for retrieval and latency metrics"""
    
    # Filter for retrieve_context tool calls
    retrieve_entries = metrics_df[metrics_df['tool_calls'].apply(
        lambda x: 'retrieve_context' in x if isinstance(x, list) else False
    )]
    
    # Retrieval scores analysis
    entries_with_scores = 0
    entries_above_threshold = 0
    
    for _, row in retrieve_entries.iterrows():
        scores = row.get('retrieval_scores', [])
        if scores and isinstance(scores, list) and len(scores) > 0:
            entries_with_scores += 1
            max_score = max(scores)
            if max_score >= retrieval_threshold:
                entries_above_threshold += 1
    
    # Tool latency analysis
    entries_with_latency = 0
    entries_below_threshold = 0
    
    for _, row in retrieve_entries.iterrows():
        latencies = row.get('tool_latencies', [])
        if latencies and isinstance(latencies, list):
            for lat_info in latencies:
                if lat_info.get('tool_name') == 'retrieve_context':
                    entries_with_latency += 1
                    if lat_info.get('latency_ms', 0) <= latency_threshold:
                        entries_below_threshold += 1
                    break
    
    # Total latency analysis
    total_entries_with_latency = 0
    total_entries_below_threshold = 0
    
    for _, row in metrics_df.iterrows():
        total_latency = row.get('observation_latency', 0)
        if total_latency > 0:
            total_entries_with_latency += 1
            if total_latency <= total_latency_threshold:
                total_entries_below_threshold += 1
    
    return {
        'total_entries': len(metrics_df),
        'retrieve_context_entries': len(retrieve_entries),
        'retrieval_analysis': {
            'entries_with_scores': entries_with_scores,
            'entries_above_threshold': entries_above_threshold,
            'percentage_above_threshold': (entries_above_threshold / entries_with_scores * 100) if entries_with_scores > 0 else 0
        },
        'latency_analysis': {
            'entries_with_latency': entries_with_latency,
            'entries_below_threshold': entries_below_threshold,
            'percentage_below_threshold': (entries_below_threshold / entries_with_latency * 100) if entries_with_latency > 0 else 0
        },
        'total_latency_analysis': {
            'entries_with_total_latency': total_entries_with_latency,
            'entries_below_threshold': total_entries_below_threshold,
            'percentage_below_threshold': (total_entries_below_threshold / total_entries_with_latency * 100) if total_entries_with_latency > 0 else 0
        }
    }

def main():
    # Setup
    langfuse = Langfuse(
        host=os.getenv("LANGFUSE_HOST", ""),
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY", "")
    )
    
    # Create groundtruth (used by run_test_queries)
    groundtruth = create_groundtruth()
    
    # Run tests
    test_results = run_test_queries()
    
    # Wait for traces
    print("Waiting 50 seconds for traces...")
    time.sleep(50)
    
    # Get recent traces
    trace_ids = get_recent_traces(langfuse, minutes=10)
    
    # Extract detailed metrics
    metrics_df = extract_detailed_metrics(langfuse, trace_ids)
    
    # Evaluate against groundtruth
    evaluation_df = evaluate_against_groundtruth(metrics_df, groundtruth)
    
    # Generate performance report
    retrieval_threshold = 0.5
    latency_threshold = 2000
    total_latency_threshold = 5000
    performance_report = generate_performance_report(metrics_df, retrieval_threshold, latency_threshold, total_latency_threshold)
    
    # Save results
    pd.DataFrame(test_results).to_csv("test_results.csv", index=False)
    metrics_df.to_csv("trace_metrics.csv", index=False)
    evaluation_df.to_csv("evaluation_results.csv", index=False)
    
    import json
    with open("performance_report.json", "w") as f:
        json.dump(performance_report, f, indent=2)
    
    # Summary
    print(f"\nResults:")
    print(f"- Test queries: {len(test_results)}")
    print(f"- Successful: {sum(1 for r in test_results if r['success'])}")
    print(f"- Recent traces: {len(trace_ids)}")
    print(f"- Extracted metrics: {len(metrics_df)}")
    print(f"- Traces found: {evaluation_df['found_trace'].sum()}/{len(evaluation_df)}")
    print(f"- Avg Precision: {evaluation_df['precision'].mean():.3f}")
    print(f"- Avg Recall: {evaluation_df['recall'].mean():.3f}")
    print(f"- Avg F1: {evaluation_df['f1'].mean():.3f}")
    
    # Performance Report
    print("\n" + "="*50)
    print("PERFORMANCE REPORT")
    print("="*50)
    ret = performance_report['retrieval_analysis']
    print(f"\nRetrieval Quality (threshold: {retrieval_threshold}):")
    print(f"- Entries with scores: {ret['entries_with_scores']}")
    print(f"- Above threshold: {ret['entries_above_threshold']} ({ret['percentage_above_threshold']:.1f}%)")
    
    lat = performance_report['latency_analysis']
    print(f"\nTool Latency Performance (threshold: {latency_threshold}ms):")
    print(f"- Entries with latency: {lat['entries_with_latency']}")
    print(f"- Below threshold: {lat['entries_below_threshold']} ({lat['percentage_below_threshold']:.1f}%)")
    
    total_lat = performance_report['total_latency_analysis']
    print(f"\nTotal Latency Performance (threshold: {total_latency_threshold}ms):")
    print(f"- Entries with total latency: {total_lat['entries_with_total_latency']}")
    print(f"- Below threshold: {total_lat['entries_below_threshold']} ({total_lat['percentage_below_threshold']:.1f}%)")
    print("="*50)

if __name__ == "__main__":
    main()