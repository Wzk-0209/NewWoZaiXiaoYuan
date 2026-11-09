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

# ==================== 打卡坐标（不再调用腾讯地图）====================
# 呈贡校区怡园内的坐标，取自你历史打卡记录
PUNCH_LAT = 24.856775
PUNCH_LON = 102.858358
PROVINCE = "云南省"
CITY = "昆明市"
DISTRICT = "呈贡区"
ADCODE = "530114"
TOWNCODE = "530114005"
TOWNSHIP = "吴家营街道"
STREET = "樱花大道"
# =====================================================================


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
        return re.search(r'JWSESSION=(.*?);', str(req.headers.get('Set-Cookie'))).group(1)
    print(f"{username}登陆失败，请检查账号密码！{req.text}")
    return False


def point_in_polygon(lon, lat, poly):
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]['longitude'], poly[i]['latitude']
        xj, yj = poly[j]['longitude'], poly[j]['latitude']
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def build_area(data):
    """从任务的 areaList 里取出自己宿舍区的多边形"""
    user_area = data.get('userArea')
    for item in (data.get('areaList') or []):
        if item.get('name') != user_area:
            continue
        if item.get('dataStr'):
            poly = json.loads(item['dataStr'])
        elif isinstance(item.get('data'), list):
            poly = item['data']
        else:
            return None
        return {"type": 1, "polygon": poly, "id": item['id'], "name": item['name']}
    return None


def build_punch_data(area):
    lat, lon = PUNCH_LAT, PUNCH_LON
    # 如果写死的坐标不在本次打卡区域内（比如换了宿舍区），自动改用该区域中心点
    if area and not point_in_polygon(lon, lat, area['polygon']):
        poly = area['polygon']
        lon = round(sum(p['longitude'] for p in poly) / len(poly), 6)
        lat = round(sum(p['latitude'] for p in poly) / len(poly), 6)
        print(f"坐标不在 {area['name']} 区域内，改用区域中心点 {lat},{lon}")
    punch = {
        "latitude": lat,
        "longitude": lon,
        "nationcode": "",
        "country": "中国",
        "province": PROVINCE,
        "citycode": "",
        "city": CITY,
        "adcode": ADCODE,
        "district": DISTRICT,
        "towncode": TOWNCODE,
        "township": TOWNSHIP,
        "streetcode": "",
        "street": STREET,
        "inArea": 1,
    }
    if area:
        punch["areaJSON"] = json.dumps(area, ensure_ascii=False)
    return punch


def do_punch(headers, username, sign_id, item_id, punch):
    h = dict(headers)
    h['Referer'] = 'https://servicewechat.com/wxce6d08f781975d91/200/page-frame.html'
    params = {'id': item_id, 'schoolId': school_id, 'signId': sign_id}
    for name, url in (("doSignByArea", f"{API}/sign/mobile/receive/doSignByArea"),
                      ("doSignByLocation", f"{API}/sign/mobile/receive/doSignByLocation")):
        try:
            res = requests.post(url, data=json.dumps(punch), headers=h, params=params)
            print(f"[{name}] {res.text}")
            if json.loads(res.text).get('code') == 0:
                print(f"{username}打卡成功！方式={name}\n")
                MsgSend("打卡成功！", f"{username}归寝打卡成功！方式={name}")
                return True
        except Exception as e:
            print(f"[{name}] 请求异常：{type(e).__name__} {e}")
    MsgSend("打卡失败！", f"{username}归寝打卡失败，请到 Actions 查看日志")
    return False


def main():
    global school_id
    username = os.environ['wzxy_username']
    school_id = get_school_id(os.environ.get('school_name'))
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

    resp = requests.get(f"{API}/sign/mobile/receive/getMySignLogs", headers=headers,
                        params={'page': 1, 'size': 10}).json()
    try:
        data = resp['data'][0]
    except Exception:
        print("没有查到打卡任务：", resp)
        return False

    if int(data.get('signStatus', 0)) != 1:
        print(f"用户已打过卡！signStatus={data.get('signStatus')}（2=已打）")
        return False

    area = build_area(data)
    print(f"打卡区域={data.get('userArea')} areaId={data.get('areaId')} 区域数据={'有' if area else '无'}")
    punch = build_punch_data(area)
    print("提交数据=", json.dumps(punch, ensure_ascii=False)[:600])
    return do_punch(headers, username, data['signId'], data['id'], punch)


if __name__ == "__main__":
    main()
