#!/usr/bin/env python
# -*- coding: utf-8 -*-
import copy
import hashlib
import hmac
import json
import math
import sys
import time
import urllib
import uuid

import requests
# Turn off InsecureRequestWarning
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from requests_toolbelt import MultipartEncoder

from InstagramAPI.constants import EXPERIMENTS, USER_AGENT, API_URL, SIG_KEY_VERSION, IG_SIG_KEY, DEVICE_SETTINTS
from .exceptions import SentryBlockException

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

try:
    from moviepy.editor import VideoFileClip
except ImportError:
    print("Fail to import moviepy. Need only for Video upload.")

# The urllib library was split into other modules from Python 2 to Python 3
if sys.version_info.major == 3:
    pass
try:
    from ImageUtils import getImageSize
except:
    # Issue 159, python3 import fix
    from .ImageUtils import getImageSize


class InstagramAPI:
    # username            # Instagram username
    # password            # Instagram password
    # debug               # Debug
    # uuid                # UUID
    # device_id           # Device ID
    # username_id         # Username ID
    # token               # _csrftoken
    # isLoggedIn          # Session status
    # rank_token          # Rank token

    def __init__(self, username, password):
        m = hashlib.md5()
        m.update(username.encode('utf-8') + password.encode('utf-8'))

        self.device_id = self.generate_device_id(m.hexdigest())

        self.username = username
        self.password = password

        self.uuid = self.generate_uuid(True)
        self.isLoggedIn = False
        self.last_response = None
        self.last_json = None
        self.s = requests.Session()

        self.username_id = None
        self.rank_token = None
        self.token = None

    def login(self, force=False):
        if not self.isLoggedIn or force:
            if self.send_request('si/fetch_headers/?challenge_type=signup&guid=' +
                                 self.generate_uuid(False), None, True):

                data = {
                    'phone_id': self.generate_uuid(True),
                    '_csrftoken': self.last_response.cookies['csrftoken'],
                    'username': self.username,
                    'guid': self.uuid,
                    'device_id': self.device_id,
                    'password': self.password,
                    'login_attempt_count': '0'
                }

                if self.send_request('accounts/login/', self.generate_signature(json.dumps(data)), True):
                    self.isLoggedIn = True
                    self.username_id = self.last_json["logged_in_user"]["pk"]
                    self.rank_token = "%s_%s" % (self.username_id, self.uuid)
                    self.token = self.last_response.cookies["csrftoken"]

                    self.sync_features()
                    print("Login success!\n")
                    return True

    def logout(self):
        self.send_request('accounts/logout/')

    def sync_features(self):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           'id': self.username_id,
                           '_csrftoken': self.token,
                           'experiments': EXPERIMENTS})
        return self.send_request('qe/sync/', self.generate_signature(data))

    def expose(self):
        data = json.dumps({'_uuid': self.uuid,
                           '_uid': self.username_id,
                           'id': self.username_id,
                           '_csrftoken': self.token,
                           'experiment': 'ig_android_profile_contextual_feed'})
        return self.send_request('qe/expose/', self.generate_signature(data))

    def upload_photo(self, photo, caption=None, upload_id=None, is_sidecar=None):
        if upload_id is None:
            upload_id = str(int(time.time() * 1000))
        data = {'upload_id': upload_id,
                '_uuid': self.uuid,
                '_csrftoken': self.token,
                'image_compression': '{"lib_name":"jt","lib_version":"1.3.0","quality":"87"}',
                'photo': ('pending_media_%s.jpg' % upload_id, open(photo, 'rb'),
                          'application/octet-stream', {'Content-Transfer-Encoding': 'binary'})}
        if is_sidecar:
            data['is_sidecar'] = '1'
        m = MultipartEncoder(data, boundary=self.uuid)
        self.s.headers.update({'X-IG-Capabilities': '3Q4=',
                               'X-IG-Connection-Type': 'WIFI',
                               'Cookie2': '$Version=1',
                               'Accept-Language': 'en-US',
                               'Accept-Encoding': 'gzip, deflate',
                               'Content-type': m.content_type,
                               'Connection': 'close',
                               'User-Agent': USER_AGENT})
        response = self.s.post(API_URL + "upload/photo/", data=m.to_string())
        if response.status_code == 200:
            if self.configure(upload_id, photo, caption):
                self.expose()
        return False

    def upload_video(self, video, thumbnail, caption=None, upload_id=None, is_sidecar=None):
        if upload_id is None:
            upload_id = str(int(time.time() * 1000))
        data = {'upload_id': upload_id,
                '_csrftoken': self.token,
                'media_type': '2',
                '_uuid': self.uuid}
        if is_sidecar:
            data['is_sidecar'] = '1'
        m = MultipartEncoder(data, boundary=self.uuid)
        self.s.headers.update({'X-IG-Capabilities': '3Q4=',
                               'X-IG-Connection-Type': 'WIFI',
                               'Host': 'i.instagram.com',
                               'Cookie2': '$Version=1',
                               'Accept-Language': 'en-US',
                               'Accept-Encoding': 'gzip, deflate',
                               'Content-type': m.content_type,
                               'Connection': 'keep-alive',
                               'User-Agent': USER_AGENT})
        response = self.s.post(API_URL + "upload/video/", data=m.to_string())
        if response.status_code == 200:
            body = json.loads(response.text)
            upload_url = body['video_upload_urls'][3]['url']
            upload_job = body['video_upload_urls'][3]['job']

            video_data = open(video, 'rb').read()
            # solve issue #85 TypeError: slice indices must be integers or None or have an __index__ method
            request_size = int(math.floor(len(video_data) / 4))
            last_request_extra = (len(video_data) - (request_size * 3))

            headers = copy.deepcopy(self.s.headers)
            self.s.headers.update({'X-IG-Capabilities': '3Q4=',
                                   'X-IG-Connection-Type': 'WIFI',
                                   'Cookie2': '$Version=1',
                                   'Accept-Language': 'en-US',
                                   'Accept-Encoding': 'gzip, deflate',
                                   'Content-type': 'application/octet-stream',
                                   'Session-ID': upload_id,
                                   'Connection': 'keep-alive',
                                   'Content-Disposition': 'attachment; filename="video.mov"',
                                   'job': upload_job,
                                   'Host': 'upload.instagram.com',
                                   'User-Agent': USER_AGENT})
            for i in range(0, 4):
                start = i * request_size
                if i == 3:
                    end = i * request_size + last_request_extra
                else:
                    end = (i + 1) * request_size
                length = last_request_extra if i == 3 else request_size
                content_range = "bytes {start}-{end}/{lenVideo}".format(start=start, end=(end - 1),
                                                                        lenVideo=len(video_data)).encode('utf-8')

                self.s.headers.update({'Content-Length': str(end - start), 'Content-Range': content_range, })
                response = self.s.post(upload_url, data=video_data[start:start + length])
            self.s.headers = headers

            if response.status_code == 200:
                if self.configure_video(upload_id, video, thumbnail, caption):
                    self.expose()
        return False

    def configure_video(self, upload_id, video, thumbnail, caption=''):
        clip = VideoFileClip(video)
        self.upload_photo(photo=thumbnail, caption=caption, upload_id=upload_id)
        data = json.dumps({
            'upload_id': upload_id,
            'source_type': 3,
            'poster_frame_index': 0,
            'length': 0.00,
            'audio_muted': False,
            'filter_type': 0,
            'video_result': 'deprecated',
            'clips': {
                'length': clip.duration,
                'source_type': '3',
                'camera_position': 'back',
            },
            'extra': {
                'source_width': clip.size[0],
                'source_height': clip.size[1],
            },
            'device': DEVICE_SETTINTS,
            '_csrftoken': self.token,
            '_uuid': self.uuid,
            '_uid': self.username_id,
            'caption': caption,
        })
        return self.send_request('media/configure/?video=1', self.generate_signature(data))

    def configure(self, upload_id, photo, caption=''):
        (w, h) = getImageSize(photo)
        data = json.dumps({'_csrftoken': self.token,
                           'media_folder': 'Instagram',
                           'source_type': 4,
                           '_uid': self.username_id,
                           '_uuid': self.uuid,
                           'caption': caption,
                           'upload_id': upload_id,
                           'device': DEVICE_SETTINTS,
                           'edits': {
                               'crop_original_size': [w * 1.0, h * 1.0],
                               'crop_center': [0.0, 0.0],
                               'crop_zoom': 1.0
                           },
                           'extra': {
                               'source_width': w,
                               'source_height': h
                           }})
        return self.send_request('media/configure/?', self.generate_signature(data))

    def generate_signature(self, data, skip_quote=False):
        if not skip_quote:
            try:
                parsed_data = urllib.parse.quote(data)
            except AttributeError:
                parsed_data = urllib.quote(data)
        else:
            parsed_data = data
        return 'ig_sig_key_version=' + SIG_KEY_VERSION + '&signed_body=' + \
               hmac.new(IG_SIG_KEY.encode('utf-8'), data.encode('utf-8'), hashlib.sha256).hexdigest() + \
               '.' + parsed_data

    def generate_device_id(self, seed):
        volatile_seed = "12345"
        m = hashlib.md5()
        m.update(seed.encode('utf-8') + volatile_seed.encode('utf-8'))
        return 'android-' + m.hexdigest()[:16]

    def generate_uuid(self, _type):
        generated_uuid = str(uuid.uuid4())
        if _type:
            return generated_uuid
        else:
            return generated_uuid.replace('-', '')

    def send_request(self, endpoint, post=None, login=False):
        verify = False  # don't show request warning

        if not self.isLoggedIn and not login:
            raise Exception("Not logged in!\n")

        self.s.headers.update({'Connection': 'close',
                               'Accept': '*/*',
                               'Content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                               'Cookie2': '$Version=1',
                               'Accept-Language': 'en-US',
                               'User-Agent': USER_AGENT})

        while True:
            try:
                if post is not None:
                    response = self.s.post(API_URL + endpoint, data=post, verify=verify)
                else:
                    response = self.s.get(API_URL + endpoint, verify=verify)
                break
            except Exception as e:
                print('Except on send_request (wait 60 sec and resend): ' + str(e))
                time.sleep(60)

        if response.status_code == 200:
            self.last_response = response
            self.last_json = json.loads(response.text)
            return True
        else:
            print("Request return " + str(response.status_code) + " error!")
            # for debugging
            try:
                self.last_response = response
                self.last_json = json.loads(response.text)
                print(self.last_json)
                if 'error_type' in self.last_json and self.last_json['error_type'] == 'sentry_block':
                    raise SentryBlockException(self.last_json['message'])
            except SentryBlockException:
                raise

            return False
