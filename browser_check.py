r"""End-to-end demo check using installed Chrome and an isolated local server.
Run manually: .venv\Scripts\python.exe browser_check.py
"""
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen
import qrcode
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / 'artifacts'
ARTIFACTS.mkdir(exist_ok=True)

def run():
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        db = directory / 'browser.db'
        command = f'import os;os.environ["SCAMSENSE_OLLAMA_MODEL"]="";import main,uvicorn;from pathlib import Path;main.DB=Path({str(db)!r});uvicorn.run(main.app,host="127.0.0.1",port=8001,log_level="error")'
        server = subprocess.Popen([sys.executable, '-c', command], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            for _ in range(100):
                try:
                    with urlopen('http://127.0.0.1:8001/health', timeout=1): break
                except OSError: time.sleep(.1)
            else: raise RuntimeError('Isolated browser test server did not start')
            qr_path = directory / 'payment.png'
            qrcode.make('upi://pay?pa=samplestore@example&pn=Sample%20Store&am=500&cu=INR').save(qr_path)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe', headless=True)
                page = browser.new_page(viewport={'width':1440,'height':1100}, device_scale_factor=1)
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto('http://127.0.0.1:8001', wait_until='networkidle')
                page.screenshot(path=str(ARTIFACTS / 'desktop.png'), full_page=True)
                page.locator('[data-scenario="refund"]').click()
                page.locator('#analyzeButton').click()
                page.locator('.risk-label').filter(has_text='HIGH RISK').wait_for()
                assert 'The story says receive' in page.locator('#resultContent').inner_text()
                page.locator('#previewPayment').click()
                assert page.locator('#paymentDialog').is_visible()
                assert 'Outgoing payment request' in page.locator('#paymentPreview').inner_text()
                page.locator('#pausePayment').click()
                page.screenshot(path=str(ARTIFACTS / 'refund-review.png'), full_page=True)
                page.locator('[data-scenario="recipient"]').click()
                page.locator('#analyzeButton').click()
                page.locator('.risk-label').filter(has_text='MEDIUM RISK').wait_for()
                assert 'Recipient differs' in page.locator('#resultContent').inner_text()
                assert 'Amount differs' in page.locator('#resultContent').inner_text()
                page.locator('[data-scenario="kyc"]').click()
                page.locator('#analyzeButton').click()
                page.locator('.risk-label').filter(has_text='MEDIUM RISK').wait_for()
                page.locator('[data-scenario="normal"]').click()
                page.locator('#saveReview').check()
                page.locator('#analyzeButton').click()
                page.locator('.risk-label').filter(has_text='LOW RISK').wait_for()
                page.locator('[data-useful="yes"]').click()
                page.wait_for_function("document.querySelector('[data-useful=yes]').disabled")
                page.locator('[data-view="history"]').click()
                page.locator('.history-card').wait_for()
                assert '1 saved reviews' in page.locator('#historySummary').inner_text()
                assert 'Feedback recorded' in page.locator('#historyList').inner_text()
                page.locator('[data-review="0"]').click()
                with page.expect_download() as download:
                    page.locator('#downloadReport').click()
                downloaded = json.loads(Path(download.value.path()).read_text())
                assert downloaded['risk'] == 'LOW'
                page.locator('#qrImage').set_input_files(str(qr_path))
                page.wait_for_function("/UPI QR decoded|Could not read QR/.test(document.getElementById('qrStatus').textContent)", timeout=40000)
                assert 'UPI QR decoded' in page.locator('#qrStatus').inner_text(), page.locator('#qrStatus').inner_text()
                assert 'samplestore@example' in page.locator('#qrData').input_value()
                # Create a readable screenshot to exercise real browser OCR.
                fixture = browser.new_page(viewport={'width':1000,'height':350},device_scale_factor=1)
                fixture.set_content('<html><body style="font:32px Arial;padding:40px;background:white;color:black">Your refund is approved.<br>Enter your UPI PIN to receive money.</body></html>')
                shot = directory / 'message.png'
                fixture.screenshot(path=str(shot))
                fixture.close()
                page.locator('[data-input="screenshot"]').click()
                page.locator('#screenshot').set_input_files(str(shot))
                page.locator('#ocrButton').click()
                page.wait_for_function("/Text extracted|OCR unavailable/.test(document.getElementById('ocrStatus').textContent)", timeout=120000)
                assert 'Text extracted' in page.locator('#ocrStatus').inner_text(), page.locator('#ocrStatus').inner_text()
                assert 'refund' in page.locator('#message').input_value().lower()
                # Original text is output through textContent/escaping, not rendered markup.
                page.locator('#message').fill('Refund approved')
                page.locator('#expectedPayee').fill('<img src=x onerror=alert(1)>')
                page.locator('#analyzeButton').click()
                page.locator('#resultContent').wait_for(state='visible')
                assert page.locator('#resultContent img').count() == 0
                page.locator('[data-view="history"]').click()
                page.once('dialog', lambda dialog: dialog.accept())
                page.locator('#deleteHistory').click()
                page.wait_for_function("document.getElementById('savedCount').textContent === '0'")
                page.locator('[data-view="check"]').click()
                page.set_viewport_size({'width':390,'height':844})
                page.locator('[data-scenario="refund"]').click()
                page.locator('#analyzeButton').click()
                page.locator('.risk-label').filter(has_text='HIGH RISK').wait_for()
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile page overflows'
                page.locator('#toast').evaluate("element => element.classList.add('hidden')")
                page.screenshot(path=str(ARTIFACTS / 'mobile.png'), full_page=True)
                assert not errors, errors
                browser.close()
                print('PASS: 4 scenarios, simulated pause, saved history, feedback, export, QR image, screenshot OCR, escaped inputs, deletion, mobile layout; no JavaScript errors.')
        finally:
            server.terminate()
            server.communicate(timeout=10)

if __name__ == '__main__':
    run()
