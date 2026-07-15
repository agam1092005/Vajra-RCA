#!/usr/bin/env python3
"""Stress testing script for Vajra RCA.
Measures and compares system performance (throughput, latency, bandwidth, CPU, and memory)
under Sequential vs. Batched modes, and benchmarks stage latencies and model throughputs.
Also simulates Kafka consumer lag profiles and sweeps batch sizes to measure fetch vs. inference latency.
"""
from __future__ import annotations

import sys
import time
import psutil
from pathlib import Path
import pandas as pd
import numpy as np

# Resolve paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.detection.isolation_forest import FlowAnomalyDetector
from app.detection.kitsune import get_kitsune_engine
from app.detection.signatures import classify as classify_signature
from app.ingestion.unsw import load_unsw_raw, flow_to_events
from app.rca.engine import RCAEngine
from app.graph.topology import TopologyGraph
from app.core.config import settings

def run_stress_test(target_rates: list[int] | None = None) -> dict:
    if target_rates is None:
        target_rates = [100, 500, 1000, 2500, 5000]
        
    print("Loading UNSW-NB15 dataset for stress testing...")
    df = load_unsw_raw(limit=15000)
    print(f"Loaded {len(df)} rows.")
    
    # Initialize and fit detector
    detector = FlowAnomalyDetector(contamination=0.15)
    print("Fitting Isolation Forest detector...")
    detector.fit(df.head(5000))
    print("Detector fitted successfully.")
    
    # Setup RCA Engine
    topo = TopologyGraph()
    topo.build_from_unsw(df.head(1000))
    rca = RCAEngine(topo)
    
    # Kitsune Engine
    kitsune = get_kitsune_engine()
    
    process = psutil.Process()
    sequential_results = []
    batched_results = []
    
    seq_latencies_5000 = []
    bat_latencies_5000 = []
    
    # ----------------------------------------------------
    # 1. RUN SEQUENTIAL INGESTION TESTS
    # ----------------------------------------------------
    print("\n" + "="*50)
    print(" Running Stress Tests: Sequential Ingestion Mode")
    print("="*50)
    
    for rate in target_rates:
        print(f"Testing Sequential Mode at target rate: {rate} ev/s...")
        process.cpu_percent(interval=None)
        time.sleep(0.1)
        
        start_time = time.time()
        processed_count = 0
        total_bytes = 0
        latencies = []
        
        interval = 1.0 / rate
        max_events = min(2000, len(df))
        max_duration = 2.0
        
        for idx in range(max_events):
            loop_start = time.time()
            row = df.iloc[idx]
            
            t0 = time.time()
            # Ingestion / Serialization
            events = flow_to_events(row)
            for ev in events:
                _ = ev.to_dict()
                
            # Score single flow
            row_df = pd.DataFrame([row])
            scored = detector.score(row_df)
            _ = scored.iloc[0]["is_anomaly"]
            
            latency_ms = (time.time() - t0) * 1000.0
            latencies.append(latency_ms)
            
            if rate == 5000:
                seq_latencies_5000.append(latency_ms)
            
            total_bytes += (float(row.get("sbytes") or 0) + float(row.get("dbytes") or 0))
            processed_count += 1
            
            elapsed = time.time() - start_time
            if elapsed >= max_duration:
                break
                
            time_spent = time.time() - loop_start
            if time_spent < interval:
                time.sleep(interval - time_spent)
                
        elapsed_actual = time.time() - start_time
        actual_throughput = processed_count / elapsed_actual if elapsed_actual > 0 else 0
        bandwidth_mbps = (total_bytes * 8) / (elapsed_actual * 1000 * 1000) if elapsed_actual > 0 else 0
        bandwidth_kb_sec = (total_bytes / 1024) / elapsed_actual if elapsed_actual > 0 else 0
        
        cpu_usage = process.cpu_percent(interval=None)
        mem_after = process.memory_info().rss / (1024 * 1024)
        
        mean_latency = np.mean(latencies) if latencies else 0
        p95_latency = np.percentile(latencies, 95) if latencies else 0
        
        print(f"  Throughput: {actual_throughput:.1f} ev/s | CPU: {cpu_usage:.1f}% | Latency: {mean_latency:.3f} ms")
        
        sequential_results.append({
            "target_rate": rate,
            "actual_throughput": round(actual_throughput, 2),
            "bandwidth_kb_s": round(bandwidth_kb_sec, 2),
            "bandwidth_mbps": round(bandwidth_mbps, 3),
            "mean_latency_ms": round(mean_latency, 3),
            "p95_latency_ms": round(p95_latency, 3),
            "cpu_percent": round(cpu_usage, 2),
            "memory_mb": round(mem_after, 2),
        })

    # ----------------------------------------------------
    # 2. RUN BATCHED INGESTION TESTS (Batch Size = 500)
    # ----------------------------------------------------
    print("\n" + "="*50)
    print(" Running Stress Tests: Batched Ingestion Mode (Batch Size = 500)")
    print("="*50)
    
    batch_size = 500
    
    for rate in target_rates:
        print(f"Testing Batched Mode at target rate: {rate} ev/s...")
        process.cpu_percent(interval=None)
        time.sleep(0.1)
        
        start_time = time.time()
        processed_count = 0
        total_bytes = 0
        latencies = []
        
        batch_interval = batch_size / rate
        max_events = min(6000, len(df))
        max_duration = 2.0
        
        idx = 0
        while idx < max_events:
            loop_start = time.time()
            batch_df = df.iloc[idx : idx + batch_size]
            if batch_df.empty:
                break
                
            t0 = time.time()
            
            # Ingestion
            for _, row in batch_df.iterrows():
                events = flow_to_events(row)
                for ev in events:
                    _ = ev.to_dict()
            
            # Score batch
            scored = detector.score(batch_df)
            _ = scored["is_anomaly"].to_numpy()
            
            # Latency per event
            batch_latency = (time.time() - t0) * 1000.0
            per_event_latency = batch_latency / len(batch_df)
            
            # Repeat the per-event latency for stats
            latencies.extend([per_event_latency] * len(batch_df))
            if rate == 5000:
                bat_latencies_5000.extend([per_event_latency] * len(batch_df))
            
            batch_bytes = batch_df["sbytes"].astype(float).sum() + batch_df["dbytes"].astype(float).sum()
            total_bytes += batch_bytes
            processed_count += len(batch_df)
            
            idx += batch_size
            
            elapsed = time.time() - start_time
            if elapsed >= max_duration:
                break
                
            time_spent = time.time() - loop_start
            if time_spent < batch_interval:
                time.sleep(batch_interval - time_spent)
                
        elapsed_actual = time.time() - start_time
        actual_throughput = processed_count / elapsed_actual if elapsed_actual > 0 else 0
        bandwidth_mbps = (total_bytes * 8) / (elapsed_actual * 1000 * 1000) if elapsed_actual > 0 else 0
        bandwidth_kb_sec = (total_bytes / 1024) / elapsed_actual if elapsed_actual > 0 else 0
        
        cpu_usage = process.cpu_percent(interval=None)
        mem_after = process.memory_info().rss / (1024 * 1024)
        
        mean_latency = np.mean(latencies) if latencies else 0
        p95_latency = np.percentile(latencies, 95) if latencies else 0
        
        print(f"  Throughput: {actual_throughput:.1f} ev/s | CPU: {cpu_usage:.1f}% | Latency: {mean_latency:.3f} ms")
        
        batched_results.append({
            "target_rate": rate,
            "actual_throughput": round(actual_throughput, 2),
            "bandwidth_kb_s": round(bandwidth_kb_sec, 2),
            "bandwidth_mbps": round(bandwidth_mbps, 3),
            "mean_latency_ms": round(mean_latency, 3),
            "p95_latency_ms": round(p95_latency, 3),
            "cpu_percent": round(cpu_usage, 2),
            "memory_mb": round(mem_after, 2),
        })

    # ----------------------------------------------------
    # 3. BENCHMARK PIPELINE STAGE LATENCY BREAKDOWN
    # ----------------------------------------------------
    print("\nBenchmarking Pipeline Stage Latencies...")
    latency_breakdown = {}
    for b_size in [100, 500, 1000]:
        batch_df = df.head(b_size)
        
        # Ingestion
        t_start = time.time()
        all_events = []
        for _, row in batch_df.iterrows():
            events = flow_to_events(row)
            for ev in events:
                all_events.append(ev.to_dict())
        t_ingest = (time.time() - t_start) * 1000.0
        
        # Inference
        t_start = time.time()
        scored = detector.score(batch_df)
        _ = scored["is_anomaly"].to_numpy()
        t_inf = (time.time() - t_start) * 1000.0
        
        # DB Write Simulation (using a standard 0.12ms per event write timing model)
        t_db = b_size * 0.12
        
        # RCA Engine
        t_start = time.time()
        from app.core.events import Event
        objs = [Event.from_dict(d) for d in all_events if "event_type" in d]
        _ = rca.find_incident_candidates(objs)
        t_rca = (time.time() - t_start) * 1000.0
        
        print(f"  Batch {b_size}: Ingest={t_ingest:.1f}ms | Inference={t_inf:.1f}ms | DB Write={t_db:.1f}ms | RCA={t_rca:.1f}ms")
        
        latency_breakdown[b_size] = {
            "ingestion": round(t_ingest, 2),
            "inference": round(t_inf, 2),
            "db_write": round(t_db, 2),
            "rca": round(t_rca, 2)
        }

    # ----------------------------------------------------
    # 4. BENCHMARK ML MODEL MAXIMUM THROUGHPUT
    # ----------------------------------------------------
    print("\nBenchmarking Max Model Throughput...")
    test_size = 3000
    sub_df = df.head(test_size)
    
    # 1. Isolation Forest
    t_start = time.time()
    scored = detector.score(sub_df)
    _ = scored["is_anomaly"].to_numpy()
    iforest_tput = test_size / (time.time() - t_start)
    
    # 2. Kitsune
    t_start = time.time()
    for idx, row in sub_df.iterrows():
        row_attrs = {
            "src_ip":        str(row.get("srcip", "")),
            "dst_ip":        str(row.get("dstip", "")),
            "src_port":      row.get("sport_i"),
            "dst_port":      row.get("dsport_i"),
            "protocol":      str(row.get("proto", "TCP")),
            "packet_length": float(row.get("sbytes") or 0),
            "timestamp":     time.time(),
        }
        _ = kitsune.process_packet(row_attrs)
    kitsune_tput = test_size / (time.time() - t_start)
    
    # 3. Rule-based Signatures
    dummy_attr = [{"feature": "Spkts", "z": 3.2, "value": 50, "baseline": 5}]
    t_start = time.time()
    for _ in range(5000):
        _ = classify_signature(dummy_attr)
    sig_tput = 5000 / (time.time() - t_start)
    
    print(f"  Isolation Forest: {iforest_tput:.1f} ev/s")
    print(f"  Kitsune: {kitsune_tput:.1f} ev/s")
    print(f"  Signatures: {sig_tput:.1f} ev/s")
    
    model_throughput = {
        "Isolation Forest": round(iforest_tput, 2),
        "Kitsune": round(kitsune_tput, 2),
        "Signatures": round(sig_tput, 2)
    }

    # ----------------------------------------------------
    # 5. SIMULATE KAFKA CONSUMER LAG PROFILES (Plot 10)
    # ----------------------------------------------------
    print("\nSimulating Kafka Consumer Lag Profiles...")
    # Time steps: 0s to 5s at 0.1s increments
    time_steps = np.arange(0, 5.1, 0.1)
    
    # Sequential processing capacity is fixed at ~73 ev/s
    seq_capacity = 73.0
    # Batched processing capacity is at ~4700 ev/s (easily clears up to 5000 ev/s)
    bat_capacity = 4700.0
    
    lag_profiles = {}
    
    # Scenarios to simulate:
    # 1. Sequential Mode at 500 ev/s
    # 2. Sequential Mode at 1000 ev/s
    # 3. Batched Mode at 1000 ev/s
    # 4. Batched Mode at 5000 ev/s
    scenarios = [
        ("Seq @ 500 ev/s", 500.0, seq_capacity),
        ("Seq @ 1000 ev/s", 1000.0, seq_capacity),
        ("Bat @ 1000 ev/s", 1000.0, bat_capacity),
        ("Bat @ 5000 ev/s", 5000.0, bat_capacity)
    ]
    
    for label, in_rate, out_cap in scenarios:
        lag_profile = []
        current_lag = 0.0
        for t in time_steps:
            if t == 0:
                lag_profile.append(0.0)
                continue
            # Over 0.1s interval, how many arrived and how many were processed
            arrived = in_rate * 0.1
            processed = min(current_lag + arrived, out_cap * 0.1)
            current_lag = max(0.0, current_lag + arrived - processed)
            lag_profile.append(round(current_lag, 2))
        lag_profiles[label] = lag_profile
        print(f"  {label} -> Final Lag after 5s: {current_lag:.0f} events")

    # ----------------------------------------------------
    # 6. SWEEP BATCH SIZES FOR FETCH VS INFERENCE (Plot 12)
    # ----------------------------------------------------
    print("\nSweeping Batch Sizes to Measure Fetch vs Inference Latencies...")
    batch_sizes = [10, 50, 100, 500, 1000]
    batch_sweep_results = {}
    
    # Kafka broker roundtrip fetch delay (simulated standard Kafka fetch delay)
    kafka_fetch_delay_ms = 2.0
    
    for bs in batch_sizes:
        # Measure inference latency for this batch size
        test_batch = df.head(bs)
        t_start = time.time()
        for _ in range(max(1, 1000 // bs)):
            scored = detector.score(test_batch)
            _ = scored["is_anomaly"].to_numpy()
        inf_time_total = (time.time() - t_start) * 1000.0
        inf_per_event = inf_time_total / (max(1, 1000 // bs) * bs)
        
        # Fetch overhead per event
        fetch_per_event = kafka_fetch_delay_ms / bs
        
        batch_sweep_results[bs] = {
            "fetch_overhead_ms": round(fetch_per_event, 4),
            "inference_ms": round(inf_per_event, 4),
            "total_ms": round(fetch_per_event + inf_per_event, 4)
        }
        print(f"  Batch {bs}: Fetch Overhead={fetch_per_event:.4f}ms/ev | Inference={inf_per_event:.4f}ms/ev")

    return {
        "sequential": sequential_results,
        "batched": batched_results,
        "seq_latencies_5000": seq_latencies_5000,
        "bat_latencies_5000": bat_latencies_5000,
        "latency_breakdown": latency_breakdown,
        "model_throughput": model_throughput,
        "lag_profiles": lag_profiles,
        "batch_sweep_results": batch_sweep_results
    }

if __name__ == "__main__":
    res = run_stress_test()
    print("Stress tests completed.")
