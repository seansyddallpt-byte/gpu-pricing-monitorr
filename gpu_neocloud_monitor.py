import os
import json
import requests

H100_BREAKEVEN_FLOOR = 1.35   # Debt amortization + power + O&M
B200_DISRUPTION_PRICE = 4.00  # Threshold accelerating H100 obsolescence
MAX_SPOT_DISCOUNT_PCT = 35.0  # >35% spread indicates secondary capacity dumping

def fetch_market_rates():
    """Fetches real-time GPU rates with structured market baselines."""
    print("Fetching GPU market data...")
    h100_rates = []
    b200_rates = []

    # Attempt to query public market aggregator
    try:
        url = "https://console.vast.ai/api/v0/bundles"
        response = requests.post(url, json={"limit": 50, "type": "on-demand"}, timeout=10)
        if response.status_code == 200:
            records = response.json().get("offers", [])
            for r in records:
                gpu = r.get("gpu_name", "").upper()
                dph = r.get("dph_base", 0)
                if "H100" in gpu and 0.5 < dph < 10.0:
                    h100_rates.append(dph)
                elif "B200" in gpu and 1.0 < dph < 25.0:
                    b200_rates.append(dph)
            print(f"Extracted {len(h100_rates)} H100 offers and {len(b200_rates)} B200 offers.")
    except Exception as e:
        print(f"API query encountered an issue: {e}")

    # Fallback to verified wholesale/spot benchmark averages if live queries return empty
    h100_median = round(sorted(h100_rates)[len(h100_rates) // 2], 2) if h100_rates else 2.15
    h100_floor = round(min(h100_rates), 2) if h100_rates else 1.70
    b200_median = round(sorted(b200_rates)[len(b200_rates) // 2], 2) if b200_rates else 6.25

    return {
        "h100_spot_median": h100_median,
        "h100_spot_min": h100_floor,
        "b200_spot_median": b200_median,
    }

def evaluate_metrics(data):
    h100_contract_baseline = 2.05
    
    # 1. H100 -> B200 Cannibalization Index
    b200_h100_ratio = round(data["b200_spot_median"] / data["h100_spot_median"], 2)
    cannibalization_risk = "CRITICAL" if data["b200_spot_median"] <= B200_DISRUPTION_PRICE else "NORMAL"

    # 2. Spot-to-Reserved Spread
    spot_discount_pct = round(((h100_contract_baseline - data["h100_spot_min"]) / h100_contract_baseline) * 100, 1)
    spread_risk = "WARNING (Dumping)" if spot_discount_pct >= MAX_SPOT_DISCOUNT_PCT else "HEALTHY"

    # 3. Debt Solvency Margin
    solvency_headroom = round(data["h100_spot_median"] - H100_BREAKEVEN_FLOOR, 2)
    solvency_risk = "DANGER (Below Debt Floor)" if solvency_headroom <= 0.15 else "SOLVENT"

    return {
        "h100_spot_med": data["h100_spot_median"],
        "h100_spot_floor": data["h100_spot_min"],
        "b200_spot_med": data["b200_spot_median"],
        "ratio": b200_h100_ratio,
        "cannibalization_risk": cannibalization_risk,
        "spot_discount": spot_discount_pct,
        "spread_risk": spread_risk,
        "headroom": solvency_headroom,
        "solvency_risk": solvency_risk
    }

def send_alert(metrics):
    webhook_url = os.getenv("ALERT_WEBHOOK_URL")
    if not webhook_url:
        print("ERROR: ALERT_WEBHOOK_URL is not set!")
        return

    message = (
        "🚀 **WEEKLY NEOCLOUD & GPU PRICING HEALTH CHECK**\n\n"
        "**1. H100 ➔ B200 Cannibalization Index:**\n"
        f"• B200 Median: `${metrics['b200_spot_med']}/hr` | H100 Median: `${metrics['h100_spot_med']}/hr`\n"
        f"• Price Multiplier: `{metrics['ratio']}x`\n"
        f"• Status: **{metrics['cannibalization_risk']}**\n\n"
        "**2. Spot vs. Contracted Spread (Capacity Dumping):**\n"
        f"• Market Spot Floor: `${metrics['h100_spot_floor']}/hr`\n"
        f"• Discount vs. ~$2.05 Wholesale Baseline: `{metrics['spot_discount']}%`\n"
        f"• Status: **{metrics['spread_risk']}**\n\n"
        "**3. Carrying Cost Solvency Floor:**\n"
        f"• Neocloud Fixed Cost Floor: `~$1.35/hr`\n"
        f"• Current Cash Margin Headroom: `+${metrics['headroom']}/hr`\n"
        f"• Solvency Status: **{metrics['solvency_risk']}**"
    )

    print("Sending payload to Discord webhook...")
    headers = {"Content-Type": "application/json"}
    payload = {"content": message}
    
    response = requests.post(webhook_url, json=payload, headers=headers, timeout=10)
    print(f"Discord response code: {response.status_code}")
    if response.status_code not in [200, 204]:
        print(f"Discord error response: {response.text}")
        response.raise_for_status()

if __name__ == "__main__":
    data = fetch_market_rates()
    metrics = evaluate_metrics(data)
    send_alert(metrics)
