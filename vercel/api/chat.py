from http.server import BaseHTTPRequestHandler
import json
import boto3
import os
import datetime

MODEL_ID = "global.anthropic.claude-opus-4-6-v1"

AWS_ACCESS_KEY = os.environ.get('AWS_ACCESS_KEY_ID', '')
AWS_SECRET_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
AWS_REGION     = os.environ.get('AWS_REGION', 'us-east-2')


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        body = json.loads(post_data.decode('utf-8'))

        messages      = body.get('messages', [])
        today = datetime.datetime.utcnow().strftime('%B %d, %Y')
        system_prompt = body.get('system_prompt', (
            f'You are XsAllu Ai, an advanced AI assistant that helps users with '
            f'coding, writing, research, problem-solving, and real-time screen analysis. '
            f'You are concise, accurate, and proactive in offering help. '
            f'Today\'s date is {today}.'
        ))

        if not AWS_ACCESS_KEY or not AWS_SECRET_KEY:
            self.send_response(500)
            self.send_header('Content-Type', 'application/x-ndjson')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write((json.dumps({
                'type': 'error',
                'error': 'AWS credentials are not configured on the server.'
            }) + '\n').encode())
            return

        try:
            client = boto3.client(
                'bedrock-runtime',
                region_name=AWS_REGION,
                aws_access_key_id=AWS_ACCESS_KEY,
                aws_secret_access_key=AWS_SECRET_KEY
            )

            request_body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 8096,
                "system": system_prompt,
                "messages": messages
            })

            response = client.invoke_model_with_response_stream(
                modelId=MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=request_body
            )
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/x-ndjson')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write((json.dumps({'type': 'error', 'error': str(e)}) + '\n').encode())
            return

        self.send_response(200)
        self.send_header('Content-Type', 'application/x-ndjson')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()

        input_tokens = 0
        output_tokens = 0

        try:
            for event in response['body']:
                chunk = event.get('chunk')
                if not chunk:
                    continue
                payload = json.loads(chunk['bytes'])
                etype = payload.get('type')

                if etype == 'message_start':
                    input_tokens = payload.get('message', {}).get('usage', {}).get('input_tokens', 0)

                elif etype == 'content_block_delta':
                    delta = payload.get('delta', {})
                    if delta.get('type') == 'text_delta':
                        text_piece = delta.get('text', '')
                        if text_piece:
                            self.wfile.write((json.dumps({'type': 'chunk', 'text': text_piece}) + '\n').encode('utf-8'))
                            self.wfile.flush()

                elif etype == 'message_delta':
                    output_tokens = payload.get('usage', {}).get('output_tokens', output_tokens)

            self.wfile.write((json.dumps({
                'type': 'done',
                'usage': {'input_tokens': input_tokens, 'output_tokens': output_tokens}
            }) + '\n').encode('utf-8'))
            self.wfile.flush()

        except Exception as e:
            try:
                self.wfile.write((json.dumps({'type': 'error', 'error': str(e)}) + '\n').encode('utf-8'))
                self.wfile.flush()
            except Exception:
                pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
