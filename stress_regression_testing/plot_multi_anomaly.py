#!/usr/bin/env python3
import os
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

def main():
    # Define the range of concurrent anomalous nodes (blast radius size)
    n_nodes = np.arange(1, 11)
    
    # Detections (incidents raised) in each mode
    # Standalone (Single Anomaly Mode): Each anomalous node raises 1 incident separately -> N incidents
    single_anomaly_detections = n_nodes
    
    # Topology-Aware Merge (Multi Anomaly Showcase Mode):
    # If 1 node is anomalous -> 1 incident.
    # If 2 or more nodes are anomalous and share a common dependency -> 1 merged incident.
    multi_anomaly_detections = np.ones_like(n_nodes)
    
    # Set up styling
    plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
    plt.figure(figsize=(9, 5.5))
    
    # Plot curves
    plt.plot(n_nodes, single_anomaly_detections, marker='o', linewidth=2.5, color='#d62728', label='Single Anomaly Mode (No Deduplication)')
    plt.plot(n_nodes, multi_anomaly_detections, marker='s', linewidth=2.5, color='#2ca02c', label='Multi Anomaly Mode (Topology-Aware Merge)')
    
    # Add titles and labels
    plt.title('Detections (Incidents Raised) vs. Number of Concurrent Anomalies', fontsize=14, fontweight='bold', pad=15)
    plt.xlabel('Number of Concurrent Anomalous Nodes (N)', fontsize=12)
    plt.ylabel('Number of Incidents Raised (Detections)', fontsize=12)
    
    plt.xticks(n_nodes)
    plt.yticks(np.arange(1, 12))
    plt.grid(True, linestyle='--', alpha=0.6)
    
    # Highlight the deduplication / alert reduction benefit
    for n in [2, 5, 10]:
        reduction = single_anomaly_detections[n-1] - multi_anomaly_detections[n-1]
        percent = (reduction / single_anomaly_detections[n-1]) * 100
        if reduction > 0:
            plt.annotate(f'-{int(percent)}% Alerts', 
                         xy=(n, multi_anomaly_detections[n-1]), 
                         xytext=(n, multi_anomaly_detections[n-1] + 1.5),
                         arrowprops=dict(facecolor='black', shrink=0.08, width=1, headwidth=6),
                         ha='center', fontsize=9, fontweight='bold', color='#1b5e20')

    plt.legend(frameon=True, fontsize=10)
    plt.tight_layout()
    
    # Save the plot
    out_dir = Path("/Users/agam1092005/Desktop/TechM_Code/vajra-rca/stress_regression_testing/graphs")
    out_dir.mkdir(parents=True, exist_ok=True)
    plot_path = out_dir / "multi_anomaly_showcase.png"
    plt.savefig(plot_path, dpi=150)
    plt.close()
    
    print(f"Graph successfully saved to: {plot_path}")
    print("\nDetection Summary Table:")
    print("-" * 55)
    print(f"{'Concurrent Anomalies (N)':<25} | {'Single Mode Detections':<22} | {'Multi Mode Detections':<20}")
    print("-" * 55)
    for n in n_nodes:
        print(f"{n:<25} | {single_anomaly_detections[n-1]:<22} | {multi_anomaly_detections[n-1]:<20}")
    print("-" * 55)

if __name__ == "__main__":
    main()
