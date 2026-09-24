"""Versioned domain knowledge; observations and strategy remain separate.

Article claims are hypotheses, not permission to execute unvalidated skills.
"""
from .stage_knowledge import VERSION as STAGE_VERSION

VERSION = 'mario-knowledge-v2'
ARTICLE = 'https://note.com/kk09020/n/n45495cd26849'
DISASSEMBLY = 'https://gist.github.com/WillSams/678a2d8a49d3f01e1d6e0362f83d1fbc'
ITEMS = frozenset({'mushroom', 'fire_flower', 'star', 'one_up', 'unknown_powerup'})
ENEMIES = frozenset({'goomba', 'green_koopa_troopa', 'red_koopa_troopa',
                     'hammer_bro', 'bloober', 'cheep_cheep', 'piranha_plant', 'bowser'})
DEFINITIONS = {
    'enemy': {'relation': 'may_damage_player', 'default_response': 'avoid_contact'},
    'item': {'relation': 'may_benefit_player', 'default_response': 'evaluate_safe_collection'},
    'goal': {'relation': 'advances_level_completion', 'default_response': 'approach'},
    'unknown': {'relation': 'unclassified_actor', 'default_response': 'treat_as_potential_hazard'},
    'pipe': {'relation': 'solid_obstacle'},
    'question_block': {'relation': 'hittable_from_below', 'contents': 'unknown_until_observed'},
}
RULES = (
    {'id': 'fire_form_and_input', 'subjects': ['fire_flower', 'player'],
     'condition': 'fireball form, fresh B press, free projectile slot',
     'effect': 'can emit fireball; max two active; holding B does not repeatedly fire',
     'source': DISASSEMBLY, 'validation': 'source_checked; live acquired form and projectile observed',
     'control_enabled': True},
    {'id': 'mushroom_reflects', 'subjects': ['mushroom', 'one_up'],
     'condition': 'moving item contacts a solid side', 'effect': 'may reverse horizontal direction',
     'source': ARTICLE, 'validation': 'article_only', 'control_enabled': False},
    {'id': 'goomba_stomp', 'subjects': ['goomba'],
     'condition': 'player lands on enemy from above', 'effect': 'enemy can be defeated; side contact is dangerous',
     'source': ARTICLE, 'validation': 'article_only', 'control_enabled': False},
    {'id': 'shell_reflects', 'subjects': ['moving_shell'],
     'condition': 'moving shell contacts wall', 'effect': 'shell can return toward player',
     'source': ARTICLE, 'validation': 'article_only; shell state decoder not implemented', 'control_enabled': False},
    {'id': 'jump_hold', 'subjects': ['player'],
     'condition': 'jump input remains held during ascent', 'effect': 'jump trajectory depends on hold duration',
     'source': ARTICLE, 'validation': 'existing_skill_replays; parameters remain empirical', 'control_enabled': True},
    {'id': 'powerup_identity', 'subjects': sorted(ITEMS),
     'condition': 'active object type 0x2e in dedicated slot 5; subtype RAM 0x39',
     'effect': '0=mushroom, 1=fire_flower, 2=star, 3=one_up; others unknown',
     'source': DISASSEMBLY, 'validation': 'source_checked_and_synthetic_RAM_tests; live_collection_unmeasured',
     'control_enabled': True},
)


def role(kind):
    if kind == 'flagpole':
        return 'goal'
    if kind in ITEMS:
        return 'item'
    return 'enemy' if kind in ENEMIES else 'unknown'


def describe(snapshot):
    objects = [dict(o.to_state(), role=role(o.kind), evidence='current_observation')
               for o in (*snapshot.enemies, *snapshot.world_objects)]
    kinds = {o['kind'] for o in objects} | {'player'}
    return {'version': VERSION, 'scope': 'SuperMarioBros-1-1-v0 / original SMB semantics',
            'stage_knowledge_version': STAGE_VERSION,
            'registered_sites': list(snapshot.powerup_sites),
            'abilities': {'can_fire': snapshot.status == 'fireball', 'active_fireballs': snapshot.active_fireballs,
                          'fire_kills_confirmed': False},
            'definitions': DEFINITIONS, 'observed_objects': objects,
            'applicable_knowledge': [r for r in RULES if kinds.intersection(r['subjects'])],
            'limitations': ['No unseen item locations are inferred.',
                            'Article-only rules do not enable controllers.',
                            'Shell states and hidden-block contents are not decoded.']}
