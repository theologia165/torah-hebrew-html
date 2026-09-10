"""Cloudflare R2 cover relay: issue a short PUT ticket and set a Notion cover."""
import hashlib, io, json, os, sys, time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import boto3
import requests
from botocore.config import Config
from PIL import Image

from prepare_notion_html import API, NOTION_VERSION, request_json

def endpoint_url():
    """Use R2's account endpoint even when a legacy secret includes /<bucket>."""
    raw=os.environ['R2_ENDPOINT'].rstrip('/')
    parsed=urlsplit(raw)
    bucket=os.environ['R2_BUCKET']
    parts=[p for p in parsed.path.split('/') if p]
    if parts == [bucket]:
        parsed=parsed._replace(path='')
    elif parts:
        raise ValueError('R2_ENDPOINT must be the account endpoint, without a bucket path')
    return urlunsplit(parsed)

def client():
    return boto3.client('s3', endpoint_url=endpoint_url(),
      aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'], aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],
      region_name='auto', config=Config(signature_version='s3v4'))

def key(run_id): return f'covers/{run_id}/cover.jpg'

def ticket(run_id, path):
    c=client(); object_key=key(run_id)
    url=c.generate_presigned_url('put_object', Params={'Bucket':os.environ['R2_BUCKET'],'Key':object_key,'ContentType':'image/jpeg'}, ExpiresIn=600, HttpMethod='PUT')
    issued_at=int(time.time())
    Path(path).write_text(json.dumps({'schema_version':'1.0-r2-cover-ticket','run_id':run_id,'object_key':object_key,'content_type':'image/jpeg','expires_in_seconds':600,'issued_at_epoch':issued_at,'expires_at_epoch':issued_at+600,'put_url':url},ensure_ascii=False,indent=2)+'\n')

def ticket_is_current(path):
    try:
        data=json.loads(Path(path).read_text())
        return data['content_type']=='image/jpeg' and data['object_key']==key(data['run_id']) and int(data['expires_at_epoch']) > time.time()+30
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False

def fetch(run_id, wait_seconds=600):
    c=client(); deadline=time.time()+wait_seconds; err=None
    while time.time()<deadline:
        try:
            data=c.get_object(Bucket=os.environ['R2_BUCKET'],Key=key(run_id))['Body'].read()
            im=Image.open(io.BytesIO(data)); im.verify()
            im=Image.open(io.BytesIO(data))
            if im.format!='JPEG' or im.size!=(1200,630): raise ValueError(f'Cover must be 1200x630 JPEG, got {im.format} {im.size}')
            return data
        except c.exceptions.NoSuchKey as e: err=e
        except Exception as e: err=e
        time.sleep(10)
    raise RuntimeError(f'WAITING_FOR_R2_COVER timed out for {key(run_id)}: {err}')

def upload_to_notion(data, token):
    """Use the same multipart /send operation that passed the 037 cover test."""
    up=request_json('POST','/file_uploads',token,json={'mode':'single_part','filename':'cover.jpg','content_type':'image/jpeg'})
    upload_id=up['id']
    headers={'Authorization':f'Bearer {token}','Notion-Version':NOTION_VERSION}
    response=requests.post(API+f'/file_uploads/{upload_id}/send',headers=headers,
        files={'file':('cover.jpg',io.BytesIO(data),'image/jpeg')},timeout=90)
    if response.status_code >= 300:
        raise RuntimeError(f'Notion cover multipart send: {response.status_code} {response.text[:600]}')
    if response.json().get('status') != 'uploaded':
        raise RuntimeError(f'Notion cover upload status: {response.json().get("status")}')
    return upload_id

def apply(run_id, page_id, delivery_path, wait_seconds=600):
    data=fetch(run_id,wait_seconds); token=os.environ['NOTION_TOKEN']
    upload_id=upload_to_notion(data,token)
    request_json('PATCH',f'/pages/{page_id}',token,json={'cover':{'type':'file_upload','file_upload':{'id':upload_id}}})
    page=request_json('GET',f'/pages/{page_id}',token)
    assert page.get('cover',{}).get('type')=='file', 'Notion cover readback was not a file'
    state=json.loads(Path(delivery_path).read_text()); prior_status=state.get('status')
    state.pop('error',None)
    state['cover']={'status':'PASS','r2_object_key':key(run_id),'sha256':hashlib.sha256(data).hexdigest(),'byte_size':len(data),'notion_file_upload_id':upload_id,'notion_cover_type':'file','r2_retention_days':14}
    if prior_status not in ('PARTIAL','FAIL'): state['status']='PASS'
    Path(delivery_path).write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':
    if sys.argv[1]=='ticket': ticket(sys.argv[2],sys.argv[3])
    elif sys.argv[1]=='apply': apply(sys.argv[2],sys.argv[3],sys.argv[4],int(sys.argv[5]) if len(sys.argv)>5 else 600)
    else: raise SystemExit('ticket RUN OUTPUT | apply RUN PAGE_ID DELIVERY_JSON [WAIT]')
