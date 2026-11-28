"""Per-shop attendance switches; dashboard and Matryoshka collection are independent."""
def enabled(config,shop):
    disabled=config.get('disabled_attendance_shops',[])
    if not isinstance(disabled,list) or any(type(value) is not int or value not in (7745,8889,9107,8353) for value in disabled):
        raise ValueError('Invalid disabled attendance shop configuration')
    if int(shop)==8353 and config.get('attendance_8353_enabled') is not True:return False
    return int(shop) not in disabled
