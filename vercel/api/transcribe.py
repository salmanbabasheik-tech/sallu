from http.server import BaseHTTPRequestHandler
import json
import boto3
import os
import base64
import time
import uuid
import urllib.request

AWS_ACCESS_KEY = os.environ.get('AWS_ACCESS_KEY_ID', '')
AWS_SECRET_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
AWS_REGION     = os.environ.get('AWS_REGION', 'us-east-2')
S3_BUCKET      = os.environ.get('S3_BUCKET', '')


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        body = json.loads(post_data.decode('utf-8'))

        audio_data = body.get('audio', '')
        audio_type = body.get('type', 'webm')

        if not AWS_ACCESS_KEY or not AWS_SECRET_KEY:
            self._err('AWS credentials not configured.')
            return
        if not S3_BUCKET:
            self._err('S3_BUCKET environment variable not set.')
            return
        if not audio_data:
            self._err('No audio received.')
            return

        try:
            raw_bytes = base64.b64decode(audio_data)
            job_name  = f'xsallu-{uuid.uuid4().hex}'
            s3_key    = f'voice/{job_name}.{audio_type}'
            media_url = f's3://{S3_BUCKET}/{s3_key}'

            s3 = boto3.client(
                's3',
                region_name=AWS_REGION,
                aws_access_key_id=AWS_ACCESS_KEY,
                aws_secret_access_key=AWS_SECRET_KEY
            )
            s3.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=raw_bytes)

            transcribe = boto3.client(
                'transcribe',
                region_name=AWS_REGION,
                aws_access_key_id=AWS_ACCESS_KEY,
                aws_secret_access_key=AWS_SECRET_KEY
            )

            media_format = 'ogg' if audio_type == 'ogg' else 'webm'

            transcribe.start_transcription_job(
                TranscriptionJobName=job_name,
                Media={'MediaFileUri': media_url},
                MediaFormat=media_format,
                LanguageCode='en-US',
                Settings={
                    'ShowSpeakerLabels': False,
                    'ChannelIdentification': False,
                    'ShowAlternatives': False,
                }
            )

            for _ in range(60):
                time.sleep(0.5)
                result = transcribe.get_transcription_job(TranscriptionJobName=job_name)
                status = result['TranscriptionJob']['TranscriptionJobStatus']
                if status == 'COMPLETED':
                    transcript_url = result['TranscriptionJob']['Transcript']['TranscriptFileUri']
                    with urllib.request.urlopen(transcript_url) as r:
                        transcript_data = json.loads(r.read())
                    text = transcript_data['results']['transcripts'][0]['transcript']
                    try:
                        s3.delete_object(Bucket=S3_BUCKET, Key=s3_key)
                    except Exception:
                        pass
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps({'text': text}).encode())
                    return
                elif status == 'FAILED':
                    break

            self._err('Transcription timed out or failed.')

        except Exception as e:
            self._err(str(e))

    def _err(self, msg):
        self.send_response(500)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({'error': msg}).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
