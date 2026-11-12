"""Bounded five-by-seven uppercase lettering for the physical Liteloop grid."""
_FONT = {
 'A':(14,17,17,31,17,17,17),'B':(30,17,17,30,17,17,30),
 'C':(14,17,16,16,16,17,14),'D':(30,17,17,17,17,17,30),
 'E':(31,16,16,30,16,16,31),'F':(31,16,16,30,16,16,16),
 'G':(14,17,16,23,17,17,15),'H':(17,17,17,31,17,17,17),
 'I':(14,4,4,4,4,4,14),'J':(7,2,2,2,18,18,12),
 'K':(17,18,20,24,20,18,17),'L':(16,16,16,16,16,16,31),
 'M':(17,27,21,21,17,17,17),'N':(17,25,21,19,17,17,17),
 'O':(14,17,17,17,17,17,14),'P':(30,17,17,30,16,16,16),
 'Q':(14,17,17,17,21,18,13),'R':(30,17,17,30,20,18,17),
 'S':(15,16,16,14,1,1,30),'T':(31,4,4,4,4,4,4),
 'U':(17,17,17,17,17,17,14),'V':(17,17,17,17,17,10,4),
 'W':(17,17,17,21,21,21,10),'X':(17,17,10,4,10,17,17),
 'Y':(17,17,10,4,4,4,4),'Z':(31,1,2,4,8,16,31),
 '0':(14,17,19,21,25,17,14),'1':(4,12,4,4,4,4,14),
 '2':(14,17,1,2,4,8,31),'3':(30,1,1,14,1,1,30),
 '4':(2,6,10,18,31,2,2),'5':(31,16,16,30,1,1,30),
 '6':(14,16,16,30,17,17,14),'7':(31,1,2,4,8,8,8),
 '8':(14,17,17,14,17,17,14),'9':(14,17,17,15,1,1,14),
 '-':(0,0,0,31,0,0,0),"'":(4,4,8,0,0,0,0),
 '.':(0,0,0,0,0,6,6),'?':(14,17,1,2,4,0,4),
 ' ':(0,0,0,0,0,0,0),
}
_ACCENTS = {'A':'ÀÁÂÃÄÅ','C':'Ç','E':'ÈÉÊË','I':'ÌÍÎÏ',
            'N':'Ñ','O':'ÒÓÔÕÖØ','U':'ÙÚÛÜ','Y':'ÝŸ'}


def caller_text(value):
    raw = value[:96].strip() if isinstance(value, str) else ''
    if not any(character.isalpha() for character in raw) or raw.lower() in (
            'unknown', 'unknown caller', 'anonymous', 'withheld', 'private',
            'private number', 'unavailable', 'incoming call', 'external'):
        raw = 'Incoming call'
    result = []
    for character in raw.upper():
        if character in ('’', '‘'):
            character = "'"
        for base, variants in _ACCENTS.items():
            if character in variants:
                character = base
                break
        result.append(character if character in _FONT else '?' if character.isalpha() else ' ')
    return ' '.join(''.join(result).split())[:48]


def notification_text(item):
    """Printable native ASCII, bounded to155 bytes plus the hardware NUL."""
    raw=str(item.get('title') or 'Notification')
    progress=item.get('progress')
    if isinstance(progress,(int,float)) and not isinstance(progress,bool) and 0<=progress<=100:
        raw+=' %d%%'%round(progress)
    raw+=' - '+str(item.get('body') or '')
    if item.get('priority')==5:raw='URGENT: '+raw
    result=[]
    for character in raw[:640]:
        if character in ('’','‘'):character="'"
        for base,variants in _ACCENTS.items():
            if character.upper() in variants:
                character=base if character.isupper() else base.lower()
                break
        result.append(character if 32<=ord(character)<=126 else '?' if character.isalpha() else ' ')
    text=' '.join(''.join(result).split()) or 'Notification'
    return text[:152]+'...' if len(text)>155 else text


def columns(text):
    result = []
    for character in text[:48]:
        rows = _FONT.get(character, _FONT['?'])
        for column in range(5):
            result.append(sum(1 << row for row in range(7) if rows[row] & (1 << (4-column))))
        result.append(0)
    return tuple(result) + (0,) * 18


_DIGITS = ('111101101101111','010110010010111','111001111100111',
           '111001111001111','101101111001001','111100111001111',
           '111100111101111','111001001001001','111101111101111','111101111001111')

def timer_bits(seconds, grid):
    """Four3x5 digits plus narrow colon fit17 columns; bit mode is PWM255."""
    seconds=max(0,int(seconds))
    minutes=seconds//60
    # MM:SS up to99:59, then HH:MM; LCD retains full H:MM:SS.
    digits=('%02d%02d' % (minutes,seconds%60) if minutes<100 else
            '%02d%02d' % (min(99,seconds//3600),minutes%60))
    packet=bytearray(20)
    for digit,x in zip(digits,(0,4,10,14)):
        glyph=_DIGITS[int(digit)]
        for y in range(5):
            for col in range(3):
                index=grid[(y+2)*18+x+col]
                if index>=0 and glyph[y*3+col]=='1':packet[index//8]|=128>>(index%8)
    for y in (3,5):
        index=grid[y*18+8]
        packet[index//8]|=128>>(index%8)
    return digits,bytes(packet)
