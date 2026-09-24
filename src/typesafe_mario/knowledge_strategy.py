"""Replaceable collection policy; object definitions live in knowledge.py."""
VERSION = 'safe-upgrade-v1'


def collectible(snapshot):
    """Conservative replaceable strategy: nearby upgrade on verified level floor."""
    if not snapshot.grounded or abs(snapshot.horizontal_speed) > 1:
        return None
    if any(-48 <= e.dx_pixels <= 96 for e in snapshot.enemies):
        return None
    rows = snapshot.local_grid
    pos = next(((r, row.index('M')) for r, row in enumerate(rows) if 'M' in row), None)
    if pos is None:
        return None
    from .state import is_solid
    r, c = pos
    floor = next((i for i in range(r+1, len(rows)) if is_solid(rows[i][c])), None)
    if floor is None or c+4 >= len(rows[0]):
        return None
    # Include a margin beyond the item; reject drops, pits and low ceilings.
    if not all(is_solid(rows[floor][j]) and
               all(not is_solid(rows[i][j]) for i in range(max(0, floor-3), floor))
               for j in range(c, c+5)):
        return None
    wanted = 'mushroom' if snapshot.status == 'small' else 'fire_flower' if snapshot.status == 'tall' else None
    return next((o for o in snapshot.world_objects if o.kind == wanted
                 and 0 <= o.dx_pixels <= 48 and abs(o.dy_pixels-8) <= 12), None)
