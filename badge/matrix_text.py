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


def columns(text):
    result = []
    for character in text[:48]:
        rows = _FONT.get(character, _FONT['?'])
        for column in range(5):
            result.append(sum(1 << row for row in range(7) if rows[row] & (1 << (4-column))))
        result.append(0)
    return tuple(result) + (0,) * 18
