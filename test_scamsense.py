import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import main
from fraud_engine import analyze_message, parse_payment, next_step, finalize_assessment

class AnalysisTests(unittest.TestCase):
    def test_task_keywords_with_outgoing_upi_are_high(self):
        keywords=['task','job','deposit','commission','tier','withdrawal access','youtube liking','telegram','investment','guaranteed returns']
        for keyword in keywords:
            with self.subTest(keyword=keyword):
                result=analyze_message('Discuss '+keyword, 'upi://pay?pa=worker@example&pn=Worker&am=500')
                matches=[item for item in result['evidence'] if item['code']=='task_investment_payment']
                self.assertEqual(len(matches),1)
                self.assertEqual(matches[0]['weight'],50)
                self.assertEqual(matches[0]['severity'],'HIGH')
                self.assertEqual(result['risk'],'HIGH')
                self.assertGreaterEqual(result['score'],75)
                self.assertTrue(result['recommendation'].startswith('Stop.'))

    def test_task_deposit_context_counted_once(self):
        result=analyze_message('Complete tasks for commissions.', 'upi://pay?pa=worker@example&am=500', context='Telegram job: deposit to unlock tier 2 and withdrawal\naccess.')
        self.assertEqual(sum(item['weight'] for item in result['evidence'] if item['code']=='task_investment_payment'),50)
        self.assertIn('withdrawal access',next(item['detail'] for item in result['evidence'] if item['code']=='task_investment_payment'))

    def test_task_rule_requires_outgoing_payment(self):
        for qr in ['', 'https://example.com', 'upi://collect?pa=worker@example']:
            result=analyze_message('Task deposit for Telegram commissions.',qr)
            self.assertNotIn('task_investment_payment',[item['code'] for item in result['evidence']])

    def test_task_rule_uses_word_boundaries(self):
        result=analyze_message('Multitasking commissioner at the frontier depository.', 'upi://pay?pa=shop@example&am=500')
        self.assertNotIn('task_investment_payment',[item['code'] for item in result['evidence']])

    def test_fastag_kyc_blocking_pressure_is_high_without_model(self):
        result=analyze_message('URGENT! Your FASTag KYC has expired. Update KYC immediately or your FASTag will be blocked.')
        self.assertEqual(result['risk'],'HIGH')
        self.assertGreaterEqual(result['score'],75)
        self.assertIn('fastag_kyc',[item['code'] for item in result['evidence']])
        self.assertIn('FASTag issuer',result['recommendation'])

    def test_ordinary_fastag_notice_is_not_blocking_pressure(self):
        result=analyze_message('You can review your FASTag KYC details in the official app when convenient.')
        self.assertNotIn('fastag_kyc',[item['code'] for item in result['evidence']])

    def test_generic_decoy_alone_has_high_severity_floor(self):
        result=analyze_message('Payment details','upi://pay?pa=merchant@okicici&pn=FASTagKYCHelpdesk&am=10')
        self.assertEqual(result['rule_score'],20)
        self.assertEqual(result['risk'],'HIGH')
        self.assertGreaterEqual(result['score'],75)
        self.assertIn('high_severity_rule',result['score_floor_reasons'])

    def test_final_score_floor_merges_high_model_assessment(self):
        result = dict(score=35,rule_score=35,ml_points=0,risk='MEDIUM',evidence=[],payment_details={},
                      context_review={'risk':'HIGH','claimed_intent':'unsure'})
        finalize_assessment(result)
        self.assertEqual((result['risk'],result['score']),('HIGH',75))
        self.assertEqual(result['base_score'],35)
        self.assertIn('validated_llm_high',result['score_floor_reasons'])
        self.assertTrue(result['recommendation'].startswith('Stop.'))

    def test_high_floor_preserves_stronger_scores_and_caps_at_100(self):
        for score,expected in [(95,95),(150,100)]:
            result = dict(score=score,rule_score=score,ml_points=0,risk='HIGH',evidence=[],context_review={'risk':'HIGH'})
            finalize_assessment(result)
            self.assertEqual(result['score'],expected)
        result['context_review']={'risk':'LOW'}
        finalize_assessment(result)
        self.assertEqual(result['score'],100)

    def test_high_severity_floor_does_not_depend_on_rule_weight(self):
        result = dict(score=5,rule_score=5,ml_points=0,risk='LOW',evidence=[{'code':'utility_verification','severity':'HIGH'}],payment_details={'amount':'10','currency':'INR'})
        finalize_assessment(result)
        self.assertEqual((result['risk'],result['score']),('HIGH',75))
        self.assertIn('high_severity_rule',result['score_floor_reasons'])

    def test_utility_verification_lure_is_high_without_llm(self):
        result = analyze_message('Pay ₹10 to verify your electricity account.', 'upi://pay?pa=agent@example&pn=ElectricityBoardHelpdesk&am=10.00', intent='send')
        self.assertEqual(result['risk'],'HIGH')
        self.assertGreaterEqual(result['score'],75)
        self.assertIn('utility_verification',[item['code'] for item in result['evidence']])
        self.assertTrue(result['recommendation'].startswith('Stop.'))
        self.assertIn('₹10 scan-to-pay verification',result['recommendation'])
        self.assertIn('This QR code will deduct money',result['recommendation'])
        self.assertIn('if you authorize',result['recommendation'])

    def test_ordinary_utility_bill_is_not_verification_scam(self):
        result = analyze_message('Please pay your monthly electricity bill of 500.', 'upi://pay?pa=power@example&pn=PowerCompany&am=500', intent='send')
        self.assertNotIn('utility_verification',[item['code'] for item in result['evidence']])
        self.assertEqual(result['risk'],'LOW')

    def test_utility_warning_handles_invalid_amount(self):
        result = analyze_message('Electricity verification payment', 'upi://pay?pa=agent@example&pn=ElectricityBoardHelpdesk&am=abc')
        self.assertEqual(result['risk'],'HIGH')
        self.assertIn('missing or invalid',result['recommendation'])

    def test_reported_refund_decoy_without_pin_is_high(self):
        result = analyze_message('Your refund of ₹5,000 is approved. Scan this QR to receive your money',
                                 'upi://pay?pa=merchant@okicici&pn=RefundDept&am=5000.00')
        self.assertEqual(result['risk'], 'HIGH')
        self.assertGreaterEqual(result['score'], 95)
        evidence = {item['code']: item for item in result['evidence']}
        self.assertEqual(evidence['intent_mismatch']['weight'], 75)
        self.assertEqual(evidence['intent_mismatch']['severity'], 'HIGH')
        self.assertEqual(evidence['generic_payee']['weight'], 20)
        self.assertTrue(result['recommendation'].startswith('Stop.'))
        self.assertIn('₹5,000.00', result['recommendation'])
        self.assertIn('if you authorize', result['recommendation'])
        self.assertNotIn('Few known warning signs', result['recommendation'])
        self.assertIn('Generic payee/transaction labels', ' '.join(result['missing_context']))

    def test_plain_outgoing_qr_with_incoming_intent_is_high(self):
        for context in ({'intent':'receive'}, {'context':'The caller promised me a refund.'}):
            result = analyze_message('Here is the code.', 'upi://pay?pa=shop@example&pn=Shop&am=500', **context)
            self.assertEqual(result['risk'], 'HIGH')
            self.assertGreaterEqual(result['score'], 75)

    def test_transaction_note_is_url_decoded(self):
        payment, supported = parse_payment('upi://pay?pa=x@example&pn=Shop&tn=Customer%20Care+Refund&am=500')
        self.assertTrue(supported)
        self.assertEqual(payment['transaction_note'], 'Customer Care Refund')

    def test_impersonation_keywords_in_name_and_note(self):
        keywords = ['RefundDept','SUPPORT','HelpDesk','Customer%20Care','KYC','Cashback','Claim','Prize','Dept']
        for field in ['pn','tn']:
            for keyword in keywords:
                with self.subTest(field=field,keyword=keyword):
                    result = analyze_message('Payment details', f'upi://pay?pa=x@example&{field}={keyword}')
                    matches = [item for item in result['evidence'] if item['code'] == 'generic_payee']
                    self.assertEqual(len(matches), 1)
                    self.assertEqual(matches[0]['weight'], 20)
                    self.assertIn('unverified', matches[0]['detail'])
                    self.assertNotIn('Few known warning signs', result['recommendation'])

    def test_name_and_note_count_once(self):
        result = analyze_message('Payment', 'upi://pay?pa=x@example&pn=RefundDept&tn=Claim+prize')
        self.assertEqual(sum(item['weight'] for item in result['evidence'] if item['code']=='generic_payee'),20)

    def test_recommendation_prioritizes_mismatch_even_with_low_aggregate(self):
        warning = next_step([{'code':'intent_mismatch'}], {'amount':'5000.00','currency':'INR'}, 'LOW')
        self.assertTrue(warning.startswith('Stop.'))
        self.assertIn('₹5,000.00', warning)

    def test_warning_handles_missing_invalid_or_extreme_amount(self):
        for amount in ['', 'NaN', 'Infinity', '-5', '1e9999999']:
            warning = next_step([{'code':'intent_mismatch'}], {'amount':amount,'currency':'INR'}, 'HIGH')
            self.assertIn('amount is missing or invalid', warning)
            self.assertNotIn('₹', warning)

    def test_explicit_purchase_with_later_cashback_does_not_become_refund(self):
        result = analyze_message('Pay 500 for groceries and get cashback later.', 'upi://pay?pa=shop@example&pn=Shop&am=500', intent='send')
        self.assertNotIn('intent_mismatch', [item['code'] for item in result['evidence']])

    def test_refund_contradiction(self):
        result = analyze_message('Enter your UPI PIN to receive your refund immediately', 'upi://pay?pa=unknown@example&pn=Unknown&am=5000')
        self.assertEqual(result['risk'], 'HIGH')
        self.assertTrue({'incoming_pin','pressure','intent_mismatch'}.issubset({e['code'] for e in result['evidence']}))

    def test_context_changes_otherwise_normal_qr(self):
        qr = 'upi://pay?pa=shop@example&pn=Shop&am=500'
        ordinary = analyze_message('Order total 500', qr, intent='send')
        incoming = analyze_message('Order total 500', qr, context='They promised a refund', intent='receive')
        self.assertGreater(incoming['score'], ordinary['score'])
        self.assertIn('intent_mismatch', [e['code'] for e in incoming['evidence']])

    def test_payee_and_amount_mismatch(self):
        result = analyze_message('Order', 'upi://pay?pa=other@example&pn=Other&am=5000', expected_payee='Sample Store', expected_amount=500)
        self.assertTrue({'payee_mismatch','amount_mismatch'}.issubset({e['code'] for e in result['evidence']}))

    def test_normal_payment(self):
        result = analyze_message('Please pay 500 for your order at Sample Store', 'upi://pay?pa=samplestore@example&pn=Sample%20Store&am=500', expected_payee='Sample Store', expected_amount=500, intent='send')
        self.assertEqual(result['risk'], 'LOW')
        self.assertEqual(result['evidence'], [])

    def test_context_only_credential_request(self):
        result = analyze_message('', context='Caller asks me to share my OTP and install AnyDesk')
        self.assertEqual(result['risk'], 'HIGH')

    def test_advance_fee(self):
        result = analyze_message('You won a prize, pay a processing fee immediately')
        self.assertIn('advance_fee', [e['code'] for e in result['evidence']])

    def test_bad_qr_is_not_payment(self):
        for qr in ['https://example.com', 'upi://collect?pa=shop@example', 'http://[broken', '']:
            self.assertFalse(parse_payment(qr)[1])

    def test_invalid_amounts_are_flagged(self):
        for amount in ['NaN','Infinity','-2','abc','0']:
            result = analyze_message('Order', f'upi://pay?pa=shop@example&am={amount}')
            self.assertIn('invalid_amount', [e['code'] for e in result['evidence']])

    def test_cap_and_missing_context(self):
        result = analyze_message('Urgent share your pin for refund update KYC install AnyDesk pay processing fee', 'upi://pay?pa=x@example&am=10', expected_amount=20, expected_payee='Store')
        self.assertEqual(result['score'], 100)
        self.assertTrue(analyze_message('', 'upi://pay?pa=shop@example')['missing_context'])

    def test_ml_metadata_is_honest(self):
        result = analyze_message('A payment')
        self.assertTrue(result['ml']['available'])
        self.assertIn('synthetic', result['ml']['training'])

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict('os.environ', {'SCAMSENSE_OLLAMA_MODEL': ''})
        self.env_patch.start()
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(main, 'DB', Path(self.temp.name) / 'test.db')
        self.db_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.env_patch.stop()
        self.client.close()
        self.db_patch.stop()
        self.temp.cleanup()

    def test_pages_and_assets(self):
        for url in ['/', '/style.css', '/app.js', '/health', '/docs']:
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_reported_refund_bug_via_api_without_llm(self):
        response = self.client.post('/analyze', json={
            'message':'Your refund of ₹5,000 is approved. Scan this QR to receive your money',
            'qr_data':'upi://pay?pa=merchant@okicici&pn=RefundDept&am=5000.00',
            'use_llm':False})
        self.assertEqual(response.status_code,200)
        result = response.json()
        self.assertEqual(result['risk'],'HIGH')
        self.assertGreaterEqual(result['score'],95)
        self.assertTrue(result['recommendation'].startswith('Stop.'))

    def test_validated_high_llm_changes_final_api_score_and_saved_review(self):
        model = dict(evidence_grounded=True,latency_ms=1,review=dict(risk='HIGH',claimed_intent='unsure',explanation='Unexpected request requires independent verification.',evidence=[{'source':'message','quote':'verify','reason':'Unexpected verification request'}]))
        with patch.dict('os.environ',{'SCAMSENSE_OLLAMA_MODEL':'test-model'}), patch('main.analyze_context',return_value=model):
            response=self.client.post('/analyze',json={'message':'Update KYC immediately to verify your account.','use_llm':True,'save_review':True})
        result=response.json()
        self.assertEqual(response.status_code,200)
        self.assertEqual(result['rule_score'],35)
        self.assertGreaterEqual(result['score'],75)
        self.assertEqual(result['risk'],'HIGH')
        self.assertTrue(result['recommendation'].startswith('Stop.'))
        self.assertGreaterEqual(self.client.get('/reviews').json()[0]['score'],75)

    def test_model_failure_keeps_rules_only_score(self):
        with patch.dict('os.environ',{'SCAMSENSE_OLLAMA_MODEL':'test-model'}), patch('main.analyze_context',side_effect=TimeoutError):
            response=self.client.post('/analyze',json={'message':'Update KYC immediately to verify your account.','use_llm':True})
        result=response.json()
        self.assertEqual(result['risk'],'MEDIUM')
        self.assertLess(result['score'],75)
        self.assertNotIn('validated_llm_high',result['score_floor_reasons'])

    def test_timeout_cannot_downgrade_fastag_or_decoy_rules(self):
        cases=[{'message':'URGENT! Your FASTag will be blocked. Update KYC immediately.'},
               {'message':'Deposit money for Telegram task commissions.','qr_data':'upi://pay?pa=worker@example&am=500'},
               {'message':'Payment details','qr_data':'upi://pay?pa=x@example&pn=FASTagKYCHelpdesk&am=10'},
               {'message':'Your refund is approved. Scan QR to receive money.','qr_data':'upi://pay?pa=x@example&am=5000'}]
        for values in cases:
            with self.subTest(values=values), patch.dict('os.environ',{'SCAMSENSE_OLLAMA_MODEL':'test-model'}), patch('main.analyze_context',side_effect=TimeoutError):
                result=self.client.post('/analyze',json={**values,'use_llm':True}).json()
            self.assertEqual(result['risk'],'HIGH')
            self.assertGreaterEqual(result['score'],75)
            self.assertEqual(result['llm_error_code'],'timeout')
            self.assertTrue(result['recommendation'].startswith('Stop.'))
            self.assertNotIn('validated_llm_high',result['score_floor_reasons'])

    def test_fenced_high_response_reaches_score_orchestrator(self):
        import io,json
        review=dict(risk='HIGH RISK',claimed_intent='unsure',explanation='Caller requests secret credentials.',evidence=[dict(source='message',quote='verify your account',reason='Unexpected request')])
        response=io.BytesIO(json.dumps({'message':{'content':'```json\n'+json.dumps(review)+'\n```'},'done_reason':'stop'}).encode())
        with patch.dict('os.environ',{'SCAMSENSE_OLLAMA_MODEL':'test-model'}), patch('llm_review.urlopen',return_value=response):
            result=self.client.post('/analyze',json={'message':'Update KYC immediately to verify your account.','use_llm':True}).json()
        self.assertEqual(result['rule_score'],35)
        self.assertEqual(result['risk'],'HIGH')
        self.assertGreaterEqual(result['score'],75)
        self.assertIn('validated_llm_high',result['score_floor_reasons'])

    def test_invalid_json_does_not_bypass_validation_or_downgrade_rules(self):
        import io
        with patch.dict('os.environ',{'SCAMSENSE_OLLAMA_MODEL':'test-model'}), patch('llm_review.urlopen',return_value=io.BytesIO(b'{broken')):
            result=self.client.post('/analyze',json={'message':'FASTag KYC urgent update immediately.','use_llm':True}).json()
        self.assertEqual(result['llm_error_code'],'invalid_json')
        self.assertEqual(result['risk'],'HIGH')
        self.assertGreaterEqual(result['score'],75)

    def test_ungrounded_high_model_does_not_receive_override(self):
        model = dict(evidence_grounded=False,review={'risk':'HIGH'})
        with patch.dict('os.environ',{'SCAMSENSE_OLLAMA_MODEL':'test-model'}), patch('main.analyze_context',return_value=model):
            result=self.client.post('/analyze',json={'message':'Update KYC immediately to verify your account.','use_llm':True}).json()
        self.assertEqual(result['risk'],'MEDIUM')
        self.assertLess(result['score'],75)
        self.assertNotIn('context_review',result)

    def test_validation(self):
        for body in [{}, {'message':'  '}, {'message':'Hi', 'expected_amount':-5}, {'message':'Hi','intent':'invalid'}, {'message':'x'*12001}]:
            self.assertEqual(self.client.post('/analyze', json=body).status_code, 422)

    def test_unsaved_and_saved_lifecycle(self):
        self.client.post('/analyze', json={'message':'Test only'})
        self.assertEqual(self.client.get('/reviews').json(), [])
        result = self.client.post('/analyze', json={'message':'Please pay for order', 'save_review':True}).json()
        saved = self.client.get('/reviews').json()
        self.assertEqual(len(saved), 1)
        self.assertNotIn('message', saved[0])
        response = self.client.post(f'/reviews/{result["id"]}/feedback', json={'label':'unsure','useful':True})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.client.get('/reviews').json()[0]['feedback']['useful'])
        self.client.delete('/reviews')
        self.assertEqual(self.client.get('/reviews').json(), [])

    def test_unknown_feedback_id(self):
        self.assertEqual(self.client.post('/reviews/missing/feedback',json={'label':'unsure','useful':False}).status_code,404)

    def test_llm_fallback(self):
        with patch.dict('os.environ', {}, clear=True):
            response = self.client.post('/analyze',json={'message':'Refund pending','use_llm':True})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['explanation_source'],'Evidence template')

if __name__ == '__main__':
    unittest.main()
