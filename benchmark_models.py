"""Identical synthetic challenge benchmark for Ollama/Sarvam. No automatic paid calls.

Examples:
  python benchmark_models.py --provider ollama --model qwen3:4b --limit 6
  python benchmark_models.py --provider sarvam --model sarvam-105b --allow-paid --limit 20
"""
import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from evaluate_scenarios import CASES
from llm_review import analyze_context
from fraud_engine import analyze_message

# Labels express expected review actions, not adjudicated real-world fraud outcomes.
LABELS = ['LOW','LOW','HIGH','HIGH','HIGH','HIGH','INSUFFICIENT','MEDIUM','MEDIUM','MEDIUM','HIGH','HIGH']
EXTRA = [
    ('Refund PIN pressure', dict(message='Your refund is pending. Scan this QR and enter your UPI PIN immediately.', qr_data='upi://pay?pa=x@example&am=5000'), 'HIGH'),
    ('Ordinary store purchase', dict(message='Please pay 500 for your order at Sample Store.', intent='send', qr_data='upi://pay?pa=samplestore@example&pn=Sample%20Store&am=500', expected_payee='Sample Store', expected_amount=500), 'LOW'),
    ('KYC pressure', dict(message='URGENT update KYC immediately or your account will be blocked.'), 'MEDIUM'),
    ('Hindi safety advice', dict(message='अपना OTP किसी से साझा न करें। बैंक कभी आपका PIN नहीं मांगता।'), 'LOW'),
    ('Hindi refund scam', dict(message='रिफंड पाने के लिए यह QR स्कैन करें और अपना UPI PIN डालें।', qr_data='upi://pay?pa=x@example&am=5000'), 'HIGH'),
    ('Refund without action', dict(message='Your refund will arrive in your original bank account. No action required.'), 'LOW'),
    ('Remote access refund', dict(message='Install AnyDesk and share your screen so I can process your refund.'), 'HIGH'),
    ('Prize release fee', dict(message='You won a prize. Pay a processing fee first to receive your winnings.'), 'HIGH'),
]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--provider', choices=['ollama','sarvam'], required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--limit', type=int, default=20, choices=range(1,21), metavar='1..20')
    parser.add_argument('--timeout', type=int, default=120)
    parser.add_argument('--allow-paid', action='store_true')
    args = parser.parse_args()
    load_dotenv(Path(__file__).parent / '.env', override=False)
    if args.provider == 'sarvam' and not args.allow_paid:
        parser.error('Sarvam requires --allow-paid after the user authorizes the bounded benchmark.')
    cases = [(name,values,label) for (name,values),label in zip(CASES,LABELS)] + EXTRA
    output = Path(__file__).parent / 'artifacts' / 'benchmarks'
    output.mkdir(parents=True, exist_ok=True)
    filename = ''.join(c if c.isalnum() else '-' for c in args.model)
    path = output / f'{args.provider}-{filename}-{datetime.now().strftime("%Y%m%d-%H%M%S")}.json'
    rows = []
    for name, values, expected in cases[:args.limit]:
        baseline = analyze_message(**{'message':'', **values})
        row = dict(case=name, expected=expected, baseline_risk=baseline['risk'], baseline_correct=baseline['risk']==expected)
        try:
            result = analyze_context(values,args.provider,args.model,args.timeout)
            row.update(result, correct=result['review']['risk'] == expected)
            print(f'{len(rows)+1}/{args.limit} {name}: {result["review"]["risk"]} expected {expected}; grounded={result["evidence_grounded"]}; {result["latency_ms"]} ms',flush=True)
        except Exception as error:
            row.update(error=f'{type(error).__name__}: {error}', correct=False)
            print(f'{len(rows)+1}/{args.limit} {name}: {row["error"]}',flush=True)
        rows.append(row)
        report = dict(provider=args.provider,model=args.model,created_at=datetime.now(timezone.utc).isoformat(),
                      caveat='20 synthetic challenge cases; labels encode intended review behavior, not validated fraud accuracy.',rows=rows)
        path.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        if row.get('error') and len(rows) <= 2:
            print('Stopping early: fix provider/schema setup before further calls.',flush=True)
            break
    completed = [row for row in rows if 'error' not in row]
    summary = dict(attempted=len(rows),completed=len(completed),correct=sum(row['correct'] for row in rows),
                   baseline_correct=sum(row['baseline_correct'] for row in rows),
                   grounded=sum(row.get('evidence_grounded',False) for row in rows),
                   missed_high=sum(row['expected']=='HIGH' and row.get('review',{}).get('risk')!='HIGH' for row in rows),
                   false_alerts=sum(row['expected']=='LOW' and row.get('review',{}).get('risk') in ['HIGH','MEDIUM'] for row in rows),
                   median_latency_ms=statistics.median(row['latency_ms'] for row in completed) if completed else None,
                   first_request_ms=completed[0]['latency_ms'] if completed else None)
    report['summary']=summary
    path.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(summary),flush=True)
    print(f'Report: {path}',flush=True)

if __name__ == '__main__': main()
