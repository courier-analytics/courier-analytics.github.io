"""DS8353 fixed pool caps; current transport must be verified in the exact 1C card."""
import re


def transport_label(value):
    if not isinstance(value,str):raise ValueError('Courier transport unavailable')
    text=' '.join(re.sub(r'^\s*\d+\s*[-–]\s*','',value).casefold().split())
    if text in ('авто','авто курьер','автокурьер','мобильный авто курьер'):return 'car'
    if text in ('вело','вело курьер','велокурьер','мобильный вело курьер'):return 'bike'
    raise ValueError('Courier transport not recognized')


def read_transport(page,prefix):
    field=page.locator('[id="'+prefix+'ТипКурьера_i0"]')
    if field.count()!=1:raise ValueError('Courier transport field missing')
    field.wait_for(state='visible',timeout=10000)
    return transport_label(field.input_value())


def measure(status,seconds):
    if status!='late' or seconds is None or seconds<=15*60:return None
    if seconds>60*60:return {'operation':'set','value':1}
    return {'operation':'transport_cap','policy':'ds8353'}


def capped_target(current,seconds,transport):
    if type(current) is not int or current<1 or seconds is None or seconds<=900:raise ValueError('No verified DS8353 target')
    if seconds>3600:cap=1
    elif transport=='bike':cap=3
    elif transport=='car':cap=8
    else:raise ValueError('DS8353 transport must be verified')
    if current<=cap:raise ValueError('Current pool already at or below DS8353 cap; no increase')
    return cap
