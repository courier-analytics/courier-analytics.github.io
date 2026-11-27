"""Verify and bind the explicitly selected Telegram group, without consuming updates.

Uses the existing bot token. Never logs tokens, deletes webhooks, or changes 1C.
"""
import argparse,json,os,re,stat,urllib.request,urllib.error
from pathlib import Path
from urllib.parse import urlsplit
from send_services_photo import NoRedirect
from prepare_openvpn import private_write
ROOT=Path('/etc/superset-telegram')
TITLE='Опоздавшие'


def chat_from_link(link):
    url=urlsplit(link.strip())
    if url.scheme!='https' or url.netloc not in ('t.me','telegram.me') or url.query or url.fragment:
        raise ValueError('Use a Telegram private-group message link https://t.me/c/.../...')
    match=re.fullmatch(r'/c/([1-9]\d*)/(?:[1-9]\d*/)?[1-9]\d*/?',url.path)
    if not match:raise ValueError('Expected a private-group message link, not an invitation')
    return -int('100'+match.group(1))


def load_token(root=ROOT):
    path=root/'telegram.json';info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode&0o077 or info.st_uid!=os.geteuid():
        raise ValueError('Bot configuration owner or permissions invalid')
    token=json.loads(path.read_text())['token']
    if not isinstance(token,str) or not re.fullmatch(r'\d+:[A-Za-z0-9_-]{30,}',token):raise ValueError('Invalid stored bot token')
    return token


def api(token,method,payload=None):
    if method not in ('deleteMessage','getMe','getChat','getChatMember','getChatAdministrators','getWebhookInfo','sendMessage','getUpdates','answerCallbackQuery','editMessageReplyMarkup','editMessageText'):
        raise ValueError('Unsupported setup method')
    request=urllib.request.Request('https://api.telegram.org/bot'+token+'/'+method,
        data=json.dumps(payload or {}).encode(),headers={'Content-Type':'application/json'},method='POST')
    try:
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=25) as response:result=json.load(response)
    except urllib.error.HTTPError as error:raise RuntimeError('Telegram HTTP '+str(error.code)) from None
    except Exception:raise RuntimeError('Telegram request outcome unknown; inspect group before retrying sends') from None
    if result.get('ok') is not True:raise RuntimeError('Telegram did not confirm setup request')
    return result['result']


def verified_config(chat,bot,membership,approvers):
    if type(chat.get('id')) is not int or chat['id']>=0 or chat.get('type') not in ('group','supergroup'):
        raise ValueError('Recipient must be a group')
    if chat.get('title','').strip().casefold()!=TITLE.casefold():raise ValueError('Group title does not match Опоздавшие')
    if membership.get('user',{}).get('id')!=bot.get('id') or membership.get('status') not in ('administrator','creator'):
        raise ValueError('Bot admin rights not confirmed in selected group')
    if not approvers or any(type(i) is not int or i<=0 for i in approvers):raise ValueError('Specify responsible human reviewer IDs')
    return {'chat_id':chat['id'],'title':chat['title'],'bot_id':bot['id'],
            'approver_ids':sorted(set(approvers)),'human_review_required':True,'automatic_limit_changes':False,
            'shops':[8889,7745,9107],'start_date':'2026-11-22'}


def configure(link,approvers,root=ROOT,send_test=False):
    chat_id=chat_from_link(link);token=load_token(root)
    bot=api(token,'getMe');chat=api(token,'getChat',{'chat_id':chat_id})
    if chat.get('id')!=chat_id:raise ValueError('Telegram returned a different chat')
    member=api(token,'getChatMember',{'chat_id':chat_id,'user_id':bot['id']})
    # Display only candidate reviewer identities; never log token or webhook URL.
    if not approvers:
        admins=api(token,'getChatAdministrators',{'chat_id':chat_id})
        print(json.dumps({'chat_id':chat_id,'title':chat.get('title'),
            'human_administrators':[{'user_id':a['user']['id'],'name':' '.join(filter(None,[a['user'].get('first_name'),a['user'].get('last_name')]))}
                                    for a in admins if not a['user'].get('is_bot')]},ensure_ascii=False,indent=2))
        print('Inspection only. Choose responsible reviewer IDs; group binding not saved.')
        return None
    config=verified_config(chat,bot,member,approvers)
    for identity in config['approver_ids']:
        reviewer=api(token,'getChatMember',{'chat_id':chat_id,'user_id':identity})
        if reviewer.get('user',{}).get('is_bot') or reviewer.get('user',{}).get('id')!=identity or reviewer.get('status') not in ('administrator','creator'):
            raise ValueError('Responsible reviewer must be a human administrator of this group')
    webhook=api(token,'getWebhookInfo')
    config['existing_webhook']=bool(webhook.get('url'))
    target=root/'late-group.json'
    if target.exists():
        old=json.loads(target.read_text())
        if old.get('chat_id')!=chat_id:raise ValueError('Different group already bound; previous binding preserved')
        config['ignored_cases']=old.get('ignored_cases',[])
    private_write(target,json.dumps(config,ensure_ascii=False,indent=2))
    print('Verified group binding saved privately. Existing bot webhook and other groups unchanged.')
    if config['existing_webhook']:print('Existing webhook detected: callback handling must integrate with its owner, not replace it.')
    if send_test:
        result=api(token,'sendMessage',{'chat_id':chat_id,'text':'Группа «Опоздавшие» привязана для проверки случаев по ДС 8889, 7745 и 9107. Изменения лимитов пока не включены. Применение каждой меры потребует подтверждения ответственного.'})
        print('Group setup notice confirmed; message ID:',result.get('message_id'))
    return config


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--message-link',required=True)
    p.add_argument('--approver-id',type=int,nargs='+');p.add_argument('--send-test',action='store_true')
    args=p.parse_args();os.umask(0o077)
    try:configure(args.message_link,args.approver_id,send_test=args.send_test)
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as error:
        raise SystemExit(str(error) if isinstance(error,(ValueError,RuntimeError)) else 'Group setup failed; no 1C limits changed')
