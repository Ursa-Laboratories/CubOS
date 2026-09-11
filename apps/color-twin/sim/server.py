"""Standalone localhost service. Deliberately imports no hardware API routers."""
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from .defaults import bundle
from .demos import demos, get_demo, _ordinary_motion_metadata, _with_motion
import copy
import yaml
from .runtime import execute
from .policy import campaign

app=FastAPI(title='CubOS Color Twin — simulation only')

class YamlInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    gantry_yaml: str=Field(max_length=200000)
    deck_yaml: str=Field(max_length=200000)
    protocol_yaml: str=Field(default='',max_length=200000)
    routing: dict = Field(default_factory=dict)
    initial_position: list[float] | None = Field(default=None, min_length=3, max_length=3)

class Policy(BaseModel):
    model_config=ConfigDict(extra='forbid')
    target: str=Field(default='#b77762',pattern=r'^#[0-9a-fA-F]{6}$')
    trials: int=Field(default=8,ge=1,le=96)
    initial: int=Field(default=4,ge=1,le=12)
    total: Literal[300]=300
    acquisition: Literal['ei','lcb','random']='ei'
    exploration: float=Field(default=.05,ge=0,le=1,allow_inf_nan=False)
    seed: int=Field(default=7,ge=0,le=1000000)

class CampaignInput(YamlInput):
    policy: Policy=Field(default_factory=Policy)

@app.get('/api/twin/defaults')
def defaults(profile: str = ''):
    if profile == 'side-exit':
        # Preserve the imported prerequisite URL for existing users/tests;
        # the named three-demo catalog uses ``saved-side-exit``.
        from .side_exit import bundle as side_bundle
        return {**side_bundle(), 'id': 'side-exit-legacy', 'name': 'Legacy side-exit prerequisite', 'mode': 'side-exit'}
    return get_demo(profile).bundle()

@app.get('/api/twin/demos')
def demo_catalog():
    return {'demos': demos()}

@app.get('/api/twin/compare/ordinary')
def compare_ordinary():
    """Run the same ordinary native protocol with planning disabled/enabled."""
    demo = get_demo('ordinary-transfer')
    raw = yaml.safe_load(demo.deck_yaml)
    legacy = copy.deepcopy(raw)
    legacy.pop('motion_planning', None)
    for entry in legacy.get('labware', {}).values():
        if isinstance(entry, dict):
            entry.pop('motion', None)
            entry.pop('occupied_tip_radius_mm', None)
    legacy_run = execute(demo.gantry_yaml, yaml.safe_dump(legacy, sort_keys=False), demo.protocol_yaml, routing={'planner_enabled': False}, initial_position=demo.initial_position)
    planned_deck = yaml.safe_dump(_with_motion(yaml.safe_load(demo.deck_yaml), _ordinary_motion_metadata()), sort_keys=False)
    legacy_result = legacy_run['fluids'].get('plate.A1', {})
    planned_run = execute(demo.gantry_yaml, planned_deck, demo.protocol_yaml, routing={**demo.routing, 'planner_enabled': True}, initial_position=demo.initial_position)
    planned_result = planned_run['fluids'].get('plate.A1', {})
    legacy_inputs = {
        'gantry_yaml': demo.gantry_yaml,
        'deck_yaml': yaml.safe_dump(legacy, sort_keys=False),
        'protocol_yaml': demo.protocol_yaml,
        'initial_position': demo.initial_position,
    }
    planned_inputs = {
        'gantry_yaml': demo.gantry_yaml,
        'deck_yaml': planned_deck,
        'protocol_yaml': demo.protocol_yaml,
        'initial_position': demo.initial_position,
    }
    return {'legacy': legacy_result, 'planned': planned_result,
            'same_liquid_outcome': legacy_result == planned_result,
            'legacy_route': legacy_run.get('route'), 'planned_route': planned_run.get('route'),
            'legacy_run': legacy_run, 'planned_run': planned_run,
            'legacy_inputs': legacy_inputs, 'planned_inputs': planned_inputs}

@app.post('/api/twin/simulate')
def simulate(body: YamlInput):
    try: return execute(body.gantry_yaml,body.deck_yaml,body.protocol_yaml,routing=body.routing or None,initial_position=body.initial_position)
    except Exception as exc:
        raise HTTPException(422,detail=f'{type(exc).__name__}: {exc}') from exc

@app.post('/api/twin/campaign')
def optimize(body: CampaignInput):
    try: return campaign(body.gantry_yaml,body.deck_yaml,body.policy)
    except Exception as exc:
        raise HTTPException(422,detail=f'{type(exc).__name__}: {exc}') from exc

DIST=Path(__file__).resolve().parents[1]/'dist'
if DIST.is_dir(): app.mount('/',StaticFiles(directory=DIST,html=True),name='ui')
