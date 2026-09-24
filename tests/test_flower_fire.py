from dataclasses import replace

from test_continuous_skills import ground

from typesafe_mario.actions import Action
from typesafe_mario.continuous_skills import SkillControl, catalog
from typesafe_mario.powerup_site import observe_site
from typesafe_mario.state import EnemyObservation


def test_second_upgrade_has_live_evidence_and_conditional_contents():
    ram = bytearray(0x800)
    bx=1248
    ram[0x500+(bx//256)%2*208+7*16+(bx%256)//16]=0xC1
    sites=observe_site(ram,1200,1,1,1)
    flower=next(o for o in sites if o['block_x']==1248)
    assert flower['observation']=='unused'
    assert flower['contents_by_status']['tall']=='fire_flower'
    assert flower['contents_by_status']['small']=='mushroom'


def fire_scene():
    return replace(ground(),status='fireball',enemies=(EnemyObservation(0,6,'goomba',100,8),))


def test_fire_skill_requires_power_and_safe_distance():
    s=fire_scene()
    assert 'FireAtEnemy' in {c.name for c in catalog(s)}
    assert 'FireAtEnemy' not in {c.name for c in catalog(replace(s,status='tall'))}
    assert 'FireAtEnemy' not in {c.name for c in catalog(replace(s,enemies=(replace(s.enemies[0],dx_pixels=24),)))}


def test_fire_releases_b_between_shots_and_yields_to_close_enemy():
    s=fire_scene()
    c=SkillControl(next(c for c in catalog(s) if c.name=='FireAtEnemy'),s)
    inputs=[c.next_action(s) for _ in range(25)]
    shots=[i for i,a in enumerate(inputs) if a==Action.FIRE]
    assert len(shots)>=2
    assert all(inputs[i-1]!=Action.FIRE for i in shots if i)
    assert c.next_action(replace(s,enemies=(replace(s.enemies[0],dx_pixels=24),))) is None
    assert c.status=='yielded'


def test_flower_requires_tall_and_matching_unused_site():
    from typesafe_mario.flower_fire import flower_eligible
    from typesafe_mario.stage_knowledge import FLOWER_SITE
    s = replace(ground(), x=1244, status='tall', powerup_sites=(dict(FLOWER_SITE, observation='unused'),))
    assert flower_eligible(s)
    assert not flower_eligible(replace(s, status='small'))
    assert not flower_eligible(replace(s, powerup_sites=(dict(FLOWER_SITE, observation='used'),)))
    assert not flower_eligible(replace(s, enemies=(EnemyObservation(0,6,'goomba',20,8),)))


def test_flower_does_not_claim_success_without_fire_form():
    from typesafe_mario.flower_fire import VisitFlower
    s = replace(ground(), x=1244, status='tall')
    c = VisitFlower(s)
    c.switch('align_under_flower_block')
    assert c.next_action(s) is None
    assert c.reason == 'flower_block_not_unused'
    c = VisitFlower(s)
    assert c.next_action(replace(s,status='fireball')) is None
    assert c.reason == 'fire_form_confirmed'


def test_firing_does_not_claim_kill_on_disappearance_and_limits_two_slots():
    s = fire_scene()
    spec = next(c for c in catalog(s) if c.name=='FireAtEnemy')
    c = SkillControl(spec,s)
    assert c.next_action(replace(s,enemies=())) is None
    assert c.reason == 'target_no_longer_observed_not_confirmed_kill'
    c = SkillControl(spec,s)
    assert Action.FIRE not in [c.next_action(replace(s,active_fireballs=2)) for _ in range(24)]


def test_single_eligible_skill_does_not_call_choice_api():
    from typesafe_mario.continuous_skills import SkillSpec
    from typesafe_mario.skill_policy import TypeSafeSkillPolicy
    class Client:
        def system_one(self, **kwargs):
            raise AssertionError('Choice API cannot accept one option')
    policy=TypeSafeSkillPolicy(client=Client())
    spec=SkillSpec('Advance',120,'advance')
    chosen, decision=policy.choose_skill(ground(),[spec],[])
    assert chosen is spec
    assert decision.route=='local_single_candidate'
    assert decision.probabilities=={}


def test_flower_can_plan_waiting_before_roof_enemies_have_left():
    from typesafe_mario.flower_fire import VisitFlower, flower_eligible
    from typesafe_mario.stage_knowledge import FLOWER_SITE
    s = replace(ground(), x=1221, status='tall',
                powerup_sites=(dict(FLOWER_SITE, observation='unused'),),
                enemies=(EnemyObservation(0,6,'goomba',27,-56),))
    assert flower_eligible(s)
    c = VisitFlower(s)
    assert c.next_action(s) == Action.RIGHT
    assert c.phase == 'reach_wait_point'
    unsafe=replace(s,enemies=(EnemyObservation(0,6,'goomba',20,8),))
    assert not flower_eligible(unsafe)
    assert c.next_action(unsafe) is None
    assert c.status == 'aborted'
