"""Evidence-led review. Scores are indicators, never fraud probabilities."""
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse, parse_qs
from ml_signals import predict_signal

DIRECTION_MISMATCH_WEIGHT = 75
GENERIC_PAYEE_WEIGHT = 20
HIGH_RISK_FLOOR = 75
TASK_SCAM_WEIGHT = 50
TASK_SCAM_PATTERNS = {
    'task': r'\btasks?\b', 'job': r'\bjobs?\b', 'deposit': r'\bdeposits?\b',
    'commission': r'\bcommissions?\b', 'tier': r'\btiers?\b',
    'withdrawal access': r'\bwithdrawal[\s-]+access\b',
    'youtube liking': r'\byoutube[\s-]+lik(?:ing|es?)\b', 'telegram': r'\btelegram\b',
    'investment': r'\binvestments?\b', 'guaranteed returns': r'\bguaranteed[\s-]+returns?\b',
}
IMPERSONATION_KEYWORDS = ('refund', 'support', 'helpdesk', 'customercare', 'kyc', 'cashback', 'claim', 'prize', 'dept')

def generic_payee_signals(payment):
    """Display text can be an impersonation lure; it never verifies ownership."""
    matches = {}
    for field in ('payee_name', 'transaction_note'):
        compact = ''.join(character for character in unicodedata.normalize('NFKC', payment.get(field, '')).casefold() if character.isalnum())
        keywords = [word for word in IMPERSONATION_KEYWORDS if word in compact]
        if keywords:
            matches[field] = keywords
    return matches

def next_step(evidence, payment, risk, context_review=None):
    """Specific severe evidence takes precedence over aggregate-score wording."""
    codes = {item['code'] for item in evidence}
    if 'task_investment_payment' in codes:
        return 'Stop. Do not deposit money to unlock tasks, commissions, investment returns or withdrawal access. Do not send another payment. Verify any job or investment offer independently.'
    if 'fastag_kyc' in codes:
        return 'Stop. Do not follow this FASTag KYC request or share a PIN or OTP. Open your FASTag issuer’s official app yourself or call its known official number before paying or updating KYC.'
    llm_incoming = context_review and context_review.get('risk') == 'HIGH' and context_review.get('claimed_intent') == 'receive' and payment.get('action') == 'Outgoing payment request'
    if 'intent_mismatch' in codes or llm_incoming or 'utility_verification' in codes:
        if 'utility_verification' in codes:
            warning = 'Stop. Do not pay a scan-to-pay verification fee to a personal or unverified utility-board handle. '
        else:
            warning = 'Stop. You never need to scan a QR code or enter your UPI PIN to receive money. '
        try:
            amount = Decimal(payment.get('amount', ''))
            if not amount.is_finite() or not 0 < amount <= Decimal('100000000'):
                raise InvalidOperation
            if 'utility_verification' in codes and amount == 10:
                warning = 'Stop. Do not pay a ₹10 scan-to-pay verification fee to a personal or unverified utility-board handle. '
            currency = payment.get('currency', 'INR')
            display = f'₹{amount:,.2f}' if currency.upper() == 'INR' else f'{amount:,.2f} {currency}'
            warning += f'This QR code will deduct money from your account if you authorize the payment. Requested amount: {display}. '
        except (InvalidOperation, ValueError):
            warning += 'This QR requests money to leave your account if you authorize it; its amount is missing or invalid. '
        return warning + 'Pause before you pay. Open the official app yourself or call a known official number.'
    if 'incoming_pin' in codes or 'credentials' in codes:
        return 'Stop. Do not share an OTP, password or PIN, or enter a UPI PIN to receive money. Verify the request independently.'
    if risk == 'HIGH':
        return 'Stop. Do not proceed or share a PIN or OTP. Pause before you pay: open the official app yourself or call a known official number.'
    if 'generic_payee' in codes:
        return 'Stop. A support or refund label does not verify the recipient. Do not pay until you have confirmed the request through the official app or a known official number.'
    return {'MEDIUM': 'Pause before you pay. Confirm the sender, recipient and purpose using a known contact.', 'LOW': 'Few known warning signs were detected. Confirm the recipient and amount yourself; this does not establish payment safety.'}[risk]

def finalize_assessment(result):
    """Merge validated model/rule signals monotonically; never lower existing risk."""
    review = result.get('context_review') or {}
    base = min(100, max(0, result.get('rule_score', 0) + result.get('ml_points', 0)))
    score = min(100, max(base, result.get('score', 0)))
    reasons = []
    if any(item.get('severity') == 'HIGH' for item in result.get('evidence', [])):
        reasons.append('high_severity_rule')
    if review.get('risk') == 'HIGH':
        reasons.append('validated_llm_high')
    if base >= 60:
        reasons.append('high_heuristic_band')
    elif not reasons and (score >= HIGH_RISK_FLOOR or result.get('risk') == 'HIGH'):
        reasons.append('existing_high_assessment')
    floor = HIGH_RISK_FLOOR if reasons else 30 if review.get('risk') == 'MEDIUM' else 0
    if floor == 30:
        reasons.append('validated_llm_medium')
    score = max(score, floor)
    risk = 'HIGH' if score >= HIGH_RISK_FLOOR else 'MEDIUM' if score >= 30 else 'LOW'
    result.update(score=score, risk=risk, base_score=base, score_floor=floor, score_floor_reasons=reasons)
    result['recommendation'] = next_step(result.get('evidence', []), result.get('payment_details', {}), risk, review)
    if review.get('risk') == 'HIGH' and not any(item.get('severity') == 'HIGH' for item in result.get('evidence', [])):
        result['summary'] = 'Context analysis identified high-risk scam indicators. Stop and verify the request independently.'
    return result

def parse_payment(payload):
    try:
        parsed = urlparse(payload.strip())
    except ValueError:
        return {}, False
    if parsed.scheme.lower() != 'upi' or parsed.netloc.lower() != 'pay':
        return {}, False
    params = parse_qs(parsed.query)
    details = {key: params.get(param, [''])[0] for key, param in [('payee_address', 'pa'), ('payee_name', 'pn'), ('transaction_note', 'tn'), ('amount', 'am'), ('currency', 'cu')]}
    details['currency'] = details['currency'] or 'INR'
    details['action'] = 'Outgoing payment request'
    return details, True

def analyze_message(message, qr_data='', context='', intent='unsure', expected_payee='', expected_amount=None):
    text = (message + '\n' + context).lower()
    payment, is_upi = parse_payment(qr_data)
    evidence = []
    def add(code, weight, title, detail, source, severity='MEDIUM'):
        evidence.append(dict(code=code, weight=weight, title=title, detail=detail, source=source, severity=severity))
    story = unicodedata.normalize('NFKC', message + '\n' + context).casefold()
    task_keywords = [keyword for keyword, pattern in TASK_SCAM_PATTERNS.items() if re.search(pattern, story)]
    if is_upi and task_keywords:
        add('task_investment_payment', TASK_SCAM_WEIGHT, 'Task or investment wording paired with an outgoing payment',
            'The message/story mentions ' + ', '.join(task_keywords) + '. Combined with an outgoing UPI request, this matches a task-deposit or investment social-engineering warning pattern. Do not pay to unlock earnings or withdrawals.',
            'Message/story + decoded QR', severity='HIGH')
    incoming = intent == 'receive' or (intent != 'send' and bool(re.search(r'\b(refund|cashback|receive money|money received|refund pending|prize|lottery|reward)\b', text)))
    pin = bool(re.search(r'\b(upi pin|enter (your )?pin|share (your )?pin)\b', text))
    if incoming and pin:
        add('incoming_pin', 35, 'PIN requested to receive money', 'A UPI PIN authorizes an outgoing payment. You do not need to enter it to receive a refund.', 'Message + your context')
    if re.search(r'\b(urgent|immediately|within \d+ minutes|account blocked|act now|last chance)\b', text):
        add('pressure', 15, 'Pressure to act quickly', 'Urgent language can discourage you from checking the request independently.', 'Message + your context')
    if re.search(r'\b(kyc expired|kyc has expired|update kyc|verify your account|account will be blocked)\b', text):
        add('kyc', 20, 'Account or KYC pressure', 'Verify account requests through the official app using independently found contact details.', 'Message + your context')
    fastag = re.search(r'\b(?:fastag|fast[\s-]+tag)\b', text)
    fastag_verification = re.search(r'\b(?:kyc|verif(?:y|ication))\b', text)
    fastag_pressure = re.search(r'\b(?:blocked|suspend(?:ed|sion)?|deactivat(?:ed|ion)|urgent|immediately|within \d+ minutes)\b', text)
    if fastag and fastag_verification and fastag_pressure:
        add('fastag_kyc', 75, 'FASTag KYC blocking-pressure pattern', 'A FASTag KYC/verification request uses urgency or a blocking threat. Stop and verify through your issuer independently; do not follow the sender’s payment instructions.', 'Message + your context', severity='HIGH')
    for url in re.findall(r'https?://[^\s<>"\']+', text):
        try:
            host = (urlparse(url.rstrip('.,!')).hostname or '').lower()
        except ValueError:
            continue
        if host.endswith(('.xyz', '.top')) or ('paytm' in host and host != 'paytm.com' and not host.endswith('.paytm.com')):
            add('domain', 20, 'Suspicious link pattern', f'The domain {host} has a suspicious pattern. This is a heuristic, not a reputation check.', 'Message link')
            break
    if incoming and is_upi:
        add('intent_mismatch', DIRECTION_MISMATCH_WEIGHT, 'The story says receive. The QR says pay.', 'The UPI QR requests an outgoing payment to the listed recipient, conflicting with the incoming money described. Receiving money does not require scanning this payment QR or authorizing a debit.', 'Your intent + decoded QR', severity='HIGH')
    generic_signals = generic_payee_signals(payment) if is_upi else {}
    if generic_signals:
        labels = ', '.join(f'{field}: {payment[field]}' for field in generic_signals)
        add('generic_payee', GENERIC_PAYEE_WEIGHT, 'Generic payee or note may be an impersonation lure', f'The QR uses generic refund/support/claim wording ({labels}). These labels can be social-engineering lures, not proof of a verified business. The recipient address {payment["payee_address"] or "(missing)"} is unverified.', 'Decoded QR payee name / transaction note', severity='HIGH')
    utility_text = ' '.join([text, payment.get('payee_name', '').casefold(), payment.get('transaction_note', '').casefold()])
    utility = re.search(r'electricity|utility|power[\s_-]*(?:bill|board)|water[\s_-]*(?:bill|board)|gas[\s_-]*bill', utility_text)
    verification = re.search(r'verif(?:y|ication)|kyc|token[\s_-]*(?:fee|payment)', utility_text)
    try:
        tiny_verification = Decimal(payment.get('amount', '')) == 10
    except InvalidOperation:
        tiny_verification = False
    if is_upi and utility and verification and (generic_signals or tiny_verification or 'personal' in text):
        add('utility_verification', 75, 'Utility scan-to-pay verification lure', 'A utility verification request is paired with an outgoing QR and a generic/unverified recipient or ₹10 token payment. Stop and verify through the utility provider directly.', 'Message/context + decoded QR', severity='HIGH')
    if re.search(r'\b(share|send|tell|give)\b.{0,35}\b(otp|password|pin)\b', text):
        add('credentials', 40, 'Secret credentials requested', 'Do not share OTPs, passwords or PINs with a caller or sender.', 'Message + your context')
    if re.search(r'\b(anydesk|teamviewer|screen shar(e|ing)|remote access|rustdesk)\b', text):
        add('remote_access', 35, 'Remote access or screen sharing', 'A caller asking to view or control your device during payment is a strong warning sign.', 'Message + your context')
    if re.search(r'\b(processing fee|registration fee|release fee|advance fee)\b', text) and incoming:
        add('advance_fee', 35, 'Pay first to receive money', 'A fee demanded before a prize, reward or refund can be an advance-fee scam pattern.', 'Message + your context')
    if is_upi and not re.fullmatch(r'[^\s@]+@[^\s@]+', payment['payee_address']):
        add('invalid_payee', 15, 'Missing or malformed UPI address', 'This QR does not contain a complete recipient UPI address.', 'Decoded QR')
    normalize = lambda value: re.sub(r'[^a-z0-9]', '', value.lower())
    if expected_payee.strip() and is_upi:
        names = [normalize(payment['payee_name']), normalize(payment['payee_address'].split('@')[0])]
        if normalize(expected_payee) not in names:
            add('payee_mismatch', 25, 'Recipient differs from your expectation', f'You expected {expected_payee}, but the QR lists {payment["payee_name"] or payment["payee_address"] or "no recipient"}. This compares text, not verified ownership.', 'Expected recipient + QR')
    if is_upi and payment['amount']:
        try:
            amount = Decimal(payment['amount'])
            if not amount.is_finite() or amount <= 0: raise InvalidOperation
            if expected_amount is not None and abs(amount - Decimal(str(expected_amount))) > Decimal('0.01'):
                add('amount_mismatch', 20, 'Amount differs from your expectation', f'You expected {expected_amount}, but the QR requests {payment["amount"]} {payment["currency"]}.', 'Expected amount + QR')
        except (InvalidOperation, ValueError):
            add('invalid_amount', 15, 'Invalid payment amount', 'The QR contains an invalid payment amount.', 'Decoded QR')
    ml = predict_signal(text)
    rule_score = min(sum(item['weight'] for item in evidence), 100)
    ml_points = 10 if ml['available'] and ml['label'] == 'scam-pattern' and ml['model_score'] >= .75 else 0
    score = min(rule_score + ml_points, 100)
    gaps = []
    if not message.strip() and not context.strip(): gaps.append('No message or caller context was supplied.')
    if not is_upi: gaps.append('No supported UPI QR was supplied; payment action and recipient cannot be compared.')
    if is_upi and not expected_payee.strip():
        gaps.append('No expected recipient was supplied. Generic payee/transaction labels are not proof of identity; independently verify this recipient.' if generic_signals else 'No expected recipient was supplied; the QR name and UPI address do not verify recipient identity.')
    if is_upi and not payment['amount']: gaps.append('No QR amount specified; confirm it on the payment screen.')
    summary = ('Your stated incoming payment conflicts with an outgoing UPI request.' if incoming and is_upi else 'The information contains warning signs that need independent verification.' if evidence else 'No strong rule-based warning signs were found; recipient ownership remains unverified.')
    result = dict(score=score, risk='LOW', rule_score=rule_score, ml_points=ml_points, reasons=[e['detail'] for e in evidence], signals=[e['title'] for e in evidence], evidence=evidence, recommendation='', payment_details=payment, qr_payment_detected=is_upi, intent='receive' if incoming else intent, summary=summary, missing_context=gaps, ml=ml, explanation_source='Evidence template', explanation='', limitations=['Heuristic score, not a fraud probability.', 'Recipient identity and reputation are not verified.', 'No payment is initiated, authorized or blocked.'])
    finalize_assessment(result)
    result['explanation'] = result['summary'] + ' ' + result['recommendation']
    return result
