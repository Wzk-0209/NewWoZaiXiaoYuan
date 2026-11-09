import requests
import json
import re
import os
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from base64 import b64encode
import urllib.parse

API = "https://gw.wozaixiaoyuan.com"
UA = ('Mozilla/5.0 (Linux; Android 10; WLZ-AN00 Build/HUAWEIWLZ-AN00; wv) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Version/4.0 Chrome/86.0.4240.99 XWEB/4343 MMWEBSDK/20220903 Mobile Safari/537.36 MMWEBID/4162 '
      'MicroMessenger/8.0.28.2240(0x28001C35) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64 '
      'miniProgram/wxce6d08f781975d91')


def MsgSend(title, info):
    if os.environ.get('mail_address') and os.environ.get('mail_password'):
        try:
            import yagmail
            yagmail.SMTP(os.environ['mail_address'], os.environ['mail_password'],
                         os.environ.get('mail_host') or 'smtp.qq.com').send(
                os.environ.get('receive_mail') or os.environ['mail_address'], title, info)
        except Exception as e:
            print("推送出错！", str(e))
    if os.environ.get('sct_ftqq'):
        try:
            requests.get(f'https://sctapi.ftqq.com/{os.environ["sct_ftqq"]}.send?' +
                         urllib.parse.urlencode({"title": title, "desp": info}))
        except Exception as e:
            print("推送出错！", str(e))


def encrypt(t, e):
    t = str(t)
    key = e.encode('utf-8')
    cipher = AES.new(key, AES.MODE_ECB)
    padded_text = pad(t.encode('utf-8'), AES.block_size)
    return b64encode(cipher.encrypt(padded_text)).decode('utf-8')


def get_school_id(school_name):
    headers00 = {"accept": "application/json, text/plain, */*",
                 "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 "
                               "(KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1 Edg/119.0.0.0"}
    data = requests.get(f"{API}/basicinfo/mobile/login/getSchoolList", headers=headers00).json()['data']
    for school in data:
        if school['name'] == school_name:
            return school['id']
    return None


def Login(username, password):
    key = (str(username) + "0000000000000000")[:16]
    params = {"schoolId": school_id, "username": username, "password": encrypt(password, key)}
    req = requests.post(f"{API}/basicinfo/mobile/login/username", params=params,
                        headers={'User-Agent': UA})
    text = json.loads(req.text)
    if text.get('code') == 0:
        print(f"{username}账号登陆成功！")
        jws = re.search(r'JWSESSION=(.*?);', str(req.headers.get('Set-Cookie'))).group(1)
        return jws
    print(f"{username}登陆失败，请检查账号密码！{req.text}")
    return False


def get_logs(headers):
    url = f"{API}/sign/mobile/receive/getMySignLogs"
    resp = requests.get(url, headers=headers, params={'page': 1, 'size': 10})
    print("DEBUG_LOGS_RAW=", resp.text)
    return resp.json()


def get_punch_data(location, tencentKey, area):
    geocode = requests.get("https://apis.map.qq.com/ws/geocoder/v1",
                           params={"address": location, "key": tencentKey}).json()
    if geocode.get('status') != 0:
        print("DEBUG_GEOCODE_FAIL=", geocode)
        return None
    loc = geocode['result']['location']
    rev = requests.get("https://apis.map.qq.com/ws/geocoder/v1",
                       params={"location": f"{loc['lat']},{loc['lng']}", "key": tencentKey}).json()
    if rev.get('status') != 0:
        print("DEBUG_REVGEOCODE_FAIL=", rev)
        return None
    d = rev['result']
    punch = {
        "latitude": d['location']['lat'],
        "longitude": d['location']['lng'],
        "nationcode": "",
        "country": "中国",
        "province": d['ad_info']['province'],
        "citycode": "",
        "city": d['ad_info']['city'],
        "adcode": d['ad_info']['adcode'],
        "district": d['ad_info']['district'],
        "towncode": d['address_reference']['town']['id'],
        "township": d['address_reference']['town']['title'],
        "streetcode": "",
        "street": d['address_component']['street'],
        "inArea": 1,
    }
    if area:
        punch["areaJSON"] = json.dumps(area, ensure_ascii=False)
    return punch


def try_punch(headers, username, sign_id, item_id, punch, area):
    h = dict(headers)
    h['Referer'] = 'https://servicewechat.com/wxce6d08f781975d91/200/page-frame.html'
    params = {'id': item_id, 'schoolId': school_id, 'signId': sign_id}
    attempts = [
        ("A_doSignByArea_areaJSON字符串", f"{API}/sign/mobile/receive/doSignByArea", punch, "punch"),
        ("B_doSignByArea_areaJSON对象", f"{API}/sign/mobile/receive/doSignByArea", punch, "obj"),
        ("C_doSignByLocation_带areaJSON", f"{API}/sign/mobile/receive/doSignByLocation", punch, "punch"),
        ("D_doSignByLocation_不带areaJSON", f"{API}/sign/mobile/receive/doSignByLocation", punch, "plain"),
    ]
    for name, url, body, mode in attempts:
        data = dict(body)
        if mode == "obj" and area:
            data["areaJSON"] = area
        if mode == "plain":
            data.pop("areaJSON", None)
        try:
            res = requests.post(url, data=json.dumps(data), headers=h, params=params)
            print(f"DEBUG_{name}_REQ=", json.dumps(data, ensure_ascii=False)[:1500])
            print(f"DEBUG_{name}_RESP=", res.text)
            txt = json.loads(res.text)
        except Exception as e:
            print(f"DEBUG_{name}_ERR=", type(e).__name__, str(e))
            continue
        if txt.get('code') == 0:
            print(f"{username}打卡成功！方式={name}\n")
            MsgSend("打卡成功！", f"{username}归寝打卡成功！方式={name}")
            return True
        print(f"{name} 失败：{res.text}")
    MsgSend("打卡失败！", f"{username}归寝打卡失败，四种方式均被拒绝，请查看 Actions 日志")
    return False


def main():
    global school_id
    username = os.environ['wzxy_username']
    school_id = get_school_id(os.environ.get('school_name'))
    print("DEBUG_SCHOOL_ID=", school_id)
    jws = Login(username, os.environ['wzxy_password'])
    if not jws:
        MsgSend("登陆失败！", f"{username} 登陆失败")
        return False
    headers = {
        'Host': 'gw.wozaixiaoyuan.com',
        'Connection': 'keep-alive',
        'Accept': 'application/json, text/plain, */*',
        'jwsession': jws,
        'cookie': f'JWSESSION={jws}',
        'User-Agent': UA,
        'Content-Type': 'application/json;charset=UTF-8',
        'X-Requested-With': 'com.tencent.mm',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Dest': 'empty',
        'Referer': 'https://gw.wozaixiaoyuan.com/h5/mobile/health/0.3.7/health',
        'Accept-Encoding': 'gzip, deflate',
        'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7'
    }
    logs = get_logs(headers)
    try:
        data = logs['data'][0]
    except Exception:
        print("DEBUG_NO_TASK=", json.dumps(logs, ensure_ascii=False)[:800])
        return False
    if int(data.get('signStatus', 0)) != 1:
        print("用户已打过卡！signStatus=", data.get('signStatus'))
        return False

    sign_id, item_id = data.get('signId'), data.get('id')
    user_area, area_list = data.get('userArea'), data.get('areaList') or []
    print("DEBUG_KEYS=", list(data.keys()))
    print("DEBUG_USER_AREA=", user_area, "AREA_N=", len(area_list))

    area = None
    for _ in area_list:
        if user_area == _['name']:
            dataStr = _['dataStr'] if ('dataStr' in _) else (
                '[{"longitude": %s, "latitude": %s}]' % (_['longitude'], _['latitude']))
            try:
                polygon = json.loads(dataStr)
            except Exception:
                polygon = dataStr
            area = {"type": 1, "polygon": polygon, "id": _['id'], "name": _['name']}
            break
    print("DEBUG_AREA=", json.dumps(area, ensure_ascii=False)[:1200] if area else "未匹配到 userArea")

    punch = get_punch_data(os.environ['punch_location'], os.environ['tencentKey'], area)
    if punch is None:
        return False
    print("DEBUG_PUNCH_BASE=", json.dumps(punch, ensure_ascii=False)[:1200])
    return try_punch(headers, username, sign_id, item_id, punch, area)


if __name__ == "__main__":
    main()
