"""Stage-specific instances and live evidence; independent of strategy/controllers.

The mapping is conditional: an upgrade block can reveal different items by
player status. Registered coordinates do not assert a currently present item.
"""
VERSION = 'world-1-1-sites-v2'

SITE = {'id': '1-1-opening-upgrade', 'world': 1, 'stage': 1, 'area': 1,
        'block_x': 336, 'block_screen_y': 144, 'expected_contents': 'status_dependent_upgrade',
        'source': 'local emulator RAM observation 2026-09-24; SMB SetupPowerUp',
        'validation': 'location_and_initial_tile_observed'}


CONTENTS = {'small': 'mushroom', 'tall': 'fire_flower', 'fireball': 'fire_flower'}
FLOWER_SITE = dict(SITE, id='1-1-second-upgrade', block_x=1248)
SITES = (dict(SITE, contents_by_status=CONTENTS), dict(FLOWER_SITE, contents_by_status=CONTENTS))


def observe_site(ram, x, world, stage, area):
    if (world, stage, area) != (1, 1, 1):
        return ()
    observed = []
    for site in SITES:
        status = 'unobserved'
        bx, sy = site['block_x'], site['block_screen_y']
        if ram is not None and -96 <= bx-x <= 128:
            tile = int(ram[0x500 + (bx//256)%2*208 + ((sy-32)//16)*16 + (bx%256)//16])
            status = 'unused' if tile == 0xC1 else 'used' if tile == 0xC4 else 'unknown'
        observed.append(dict(site, observation=status))
    return tuple(observed)
