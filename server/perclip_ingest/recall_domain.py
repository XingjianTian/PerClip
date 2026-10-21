"""The single deterministic Recall domain; preferences are projection-only."""
from __future__ import annotations
import hashlib, json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from typing import Iterable
from datetime import datetime, timezone
from .recall import RecallCandidate, normalized_label, safe_text

ICON_SLOTS={"topic","note","link","image","file","education","project","idea","database","web","unknown"}
def _digest(v:str)->int:return int(hashlib.sha256(v.encode()).hexdigest()[:12],16)
def stable_rotation_seed(i:str)->int:return _digest(i)%2147483647
def stable_color_slot(i:str,slot_count:int=8)->int:return _digest(i)%slot_count
def normalized_weight(v:float,m:float)->float:return round(max(0,min(1,v/m if m else 0)),6)
def topic_short_label(v:str)->str:return {"ai agent":"AI","人工智能教学应用":"AI教学","工作流设计":"工作流","论文阅读":"论文","知识图谱可视化":"图谱"}.get(normalized_label(safe_text(v,limit=24)),safe_text(v,limit=6) or "主题")
def memory_short_label(v:str)->str:return safe_text(v,limit=10) or "闪记"
def icon_slot_for(*,source_type="",label="",topic=False)->str:
    return ("education" if any(x in normalized_label(label) for x in ("教学","课程","学习")) else "topic") if topic else {"url":"web","image":"image","file":"file","text":"note"}.get(source_type,"unknown")
def label_priority_for(weight:float,*,new=False,not_viewed=False,deferred=False)->float:return round(max(0,min(1,weight+(.06 if new else 0)+(.05 if not_viewed else 0)-(.12 if deferred else 0))),6)
@dataclass(frozen=True)
class RecallTopicNode:
 id:str;label:str;short_label:str;clip_count:int;weight:float;size_weight:float;color_slot:int;icon_slot:str;label_priority:float;rotation_seed:int;last_activity_at:str;new_in_window:bool;viewed_count:int=0;deferred_count:int=0;opened_original_count:int=0;last_recalled_at:str=""
@dataclass(frozen=True)
class RecallMemoryNode:
 id:str;clip_id:str;client_request_id:str;primary_topic_id:str;topic_ids:list[str];label:str;short_label:str;summary:str;safe_excerpt:str;source_type:str;source_label:str;knowledge_base_name:str;tags:list[str];captured_at:str;recall_count:int;last_recalled_at:str;weight:float;size_weight:float;color_slot:int;icon_slot:str;label_priority:float;rotation_seed:int;view_count:int=0;defer_count:int=0;opened_original_count:int=0;last_viewed_at:str="";last_deferred_at:str=""
@dataclass(frozen=True)
class RecallRelation: source:str;target:str;type:str;weight:float
@dataclass(frozen=True)
class RecallDomainSnapshot: days:int;window_start:str;window_end:str;snapshot_key:str;topics:list[RecallTopicNode];memories:list[RecallMemoryNode];relations:list[RecallRelation]
@dataclass(frozen=True)
class ResurfaceScore: score:float;reason_codes:list[str]
def resurface_query_key(canonical_snapshot_key,*,topic_id,exclude_clip_ids,preferred_topic_ids,muted_topic_ids,effective_days):
 return hashlib.sha256(json.dumps({'v':1,'canonical':canonical_snapshot_key,'topic':topic_id,'exclude':sorted(set(exclude_clip_ids)),'preferred':sorted(set(preferred_topic_ids)),'muted':sorted(set(muted_topic_ids)),'days':effective_days},sort_keys=True,separators=(',',':')).encode()).hexdigest()[:32]
def score_resurface_memory(memory,stats,preferences,*,now):
 st=stats.get(memory.clip_id,{}) if isinstance(stats,dict) else {}; score=.25+memory.weight*.25; reasons=[]
 def parsed(value):
  try:
   item=datetime.fromisoformat(str(value).replace('Z','+00:00')); return item if item.tzinfo else None
  except (TypeError,ValueError): return None
 viewed=parsed(st.get('last_viewed_at','')); deferred=parsed(st.get('last_deferred_at',''))
 if not viewed: score+=.30; reasons.append('never_viewed')
 elif (now-viewed.astimezone(timezone.utc)).days>=7: score+=.10; reasons.append('not_viewed_recently')
 if memory.primary_topic_id in set(preferences.get('preferred_topic_ids',[])):score+=.08;reasons.append('preferred_topic')
 if memory.weight>=.7:reasons.append('content_rich')
 if st.get('opened_original_count',0):score+=.04;reasons.append('opened_original')
 if deferred and (now-deferred.astimezone(timezone.utc)).days<=3:score-=.25;reasons.append('recently_deferred')
 if st.get('defer_count',0)>=2:score-=.10;reasons.append('repeated_defer')
 return ResurfaceScore(round(max(0,min(1,score)),6),reasons)
def _key(days,start,end,cands,previous,labels,stats,history):
 s=[]
 for c in sorted(cands,key=lambda x:x.clip_id):
  st=stats.get(c.clip_id,{}) if isinstance(stats,dict) else {}; hs=history.get(c.clip_id,{}) if isinstance(history,dict) else {}
  s.append((c.clip_id,c.captured_at,[x[0] for x in c.topics],hashlib.sha256((c.title+'\x1f'+c.summary).encode()).hexdigest(),hs.get('recall_count',c.recall_count),hs.get('last_recalled_at',''),st.get('view_count',0),st.get('defer_count',0),st.get('opened_original_count',0),st.get('last_viewed_at',''),st.get('last_deferred_at','')))
 payload=(2,days,start,end,sorted(previous),sorted(labels.items()),s)
 return hashlib.sha256(json.dumps(payload,separators=(',',':')).encode()).hexdigest()[:32]
def build_recall_domain(candidates:Iterable[RecallCandidate],*,days:int,window_start:str,window_end:str,previous_window_topic_ids:set[str]|None=None,recall_stats:dict[str,object]|None=None,interaction_stats:dict[str,object]|None=None,preferences:dict[str,object]|None=None)->RecallDomainSnapshot:
 cs=sorted(candidates,key=lambda c:(-c.score,c.clip_id)); previous=previous_window_topic_ids or set(); stats=interaction_stats or {}; recalled=recall_stats or {}
 label_variants:dict[str,Counter[str]]=defaultdict(Counter)
 for c in cs:
  for i,l in c.topics: label_variants[i][l]+=1
 labels={i:sorted(v,key=lambda x:(-v[x],normalized_label(x),x))[0] for i,v in label_variants.items()}; counts=Counter(i for c in cs for i,_ in c.topics); max_count=max(counts.values(),default=1); latest={i:max(c.captured_at for c in cs if any(x==i for x,_ in c.topics)) for i in counts}
 ids=sorted(counts,key=lambda i:(-counts[i],normalized_label(labels[i]),i)); topics=[RecallTopicNode(i,labels[i],topic_short_label(labels[i]),counts[i],normalized_weight(counts[i],max_count),normalized_weight(counts[i],max_count),stable_color_slot(i),icon_slot_for(label=labels[i],topic=True),label_priority_for(normalized_weight(counts[i],max_count),new=i not in previous),stable_rotation_seed(i),latest[i],i not in previous) for i in ids]
 colors={t.id:t.color_slot for t in topics}; maximum=max((c.score for c in cs),default=1); mem=[]; rel=[]
 for c in cs:
  tids=[i for i,_ in c.topics]; primary=tids[0]; st=stats.get(c.clip_id,{}) if isinstance(stats,dict) else {}; w=normalized_weight(c.score,maximum)
  hs=recalled.get(c.clip_id,{}) if isinstance(recalled,dict) else {}; rc=hs.get('recall_count',c.recall_count) if isinstance(hs,dict) else hs
  m=RecallMemoryNode(f'clip:{c.clip_id}',c.clip_id,c.client_request_id,primary,tids,c.title,memory_short_label(c.title),safe_text(c.summary,limit=240),safe_text(c.reveal_text or c.summary,limit=400),c.source_type,c.source_app or c.source_type,c.knowledge_base_name,c.tags,c.captured_at,int(rc),str(hs.get('last_recalled_at','')) if isinstance(hs,dict) else '',w,w,colors[primary],icon_slot_for(source_type=c.source_type),label_priority_for(w,new=primary not in previous,not_viewed=not st.get('last_viewed_at'),deferred=bool(st.get('defer_count'))),stable_rotation_seed(f'clip:{c.clip_id}'),int(st.get('view_count',0)),int(st.get('defer_count',0)),int(st.get('opened_original_count',0)),str(st.get('last_viewed_at','')),str(st.get('last_deferred_at','')));mem.append(m);rel += [RecallRelation(i,m.id,'contains',1.0) for i in tids]
 pairs=Counter((a,b) for c in cs for n,a in enumerate(sorted(i for i,_ in c.topics)) for b in sorted(i for i,_ in c.topics)[n+1:]); rel += [RecallRelation(a,b,'co_occurs',normalized_weight(n,max(pairs.values()))) for (a,b),n in sorted(pairs.items())]
 def latest_activity(values):
  parsed=[]
  for value in values:
   try:
    item=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if item.tzinfo: parsed.append((item.astimezone(timezone.utc),str(value)))
   except (TypeError,ValueError): pass
  return max(parsed,default=(None,''))[1]
 topics=[replace(t,viewed_count=sum(m.view_count for m in mem if t.id in m.topic_ids),deferred_count=sum(m.defer_count for m in mem if t.id in m.topic_ids),opened_original_count=sum(m.opened_original_count for m in mem if t.id in m.topic_ids),last_recalled_at=latest_activity(m.last_recalled_at for m in mem if t.id in m.topic_ids),last_activity_at=latest_activity(v for m in mem if t.id in m.topic_ids for v in (m.captured_at,m.last_recalled_at,m.last_viewed_at,m.last_deferred_at))) for t in topics]
 return RecallDomainSnapshot(days,window_start,window_end,_key(days,window_start,window_end,cs,previous,labels,stats,recalled),topics,mem,rel)
def projection_key(snapshot,*,topic_limit,memory_limit,topic_id,include_memories,preferences):
 values={k:preferences.get(k) for k in ('include_memory_labels','visible_label_count','label_rotation_seconds','default_days')}; values['preferred_topic_ids']=sorted(set(preferences.get('preferred_topic_ids',[]))); values['muted_topic_ids']=sorted(set(preferences.get('muted_topic_ids',[]))); values.update(canonical_snapshot_key=snapshot.snapshot_key,topic_limit=topic_limit,memory_limit=memory_limit,topic_id=topic_id,include_memories=include_memories)
 return hashlib.sha256(json.dumps(values,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:32]
def domain_payload(snapshot:RecallDomainSnapshot,*,topic_limit=30,memory_limit=200,topic_id='',include_memories=True,preferences:dict[str,object]|None=None)->dict[str,object]:
 p=preferences or {}; muted=set(p.get('muted_topic_ids',[])); preferred=set(p.get('preferred_topic_ids',[])); topics=[t for t in snapshot.topics if t.id not in muted and (not topic_id or t.id==topic_id)][:topic_limit]; allowed={t.id for t in topics}; ts=[]
 for t in topics: ts.append(replace(t,label_priority=round(min(1,t.label_priority+(.08 if t.id in preferred else 0)),6)))
 candidates=[]
 for m in snapshot.memories:
  ids=[i for i in m.topic_ids if i in allowed]
  if ids and include_memories: candidates.append(replace(m,primary_topic_id=m.primary_topic_id if m.primary_topic_id in allowed else ids[0],topic_ids=ids,label_priority=round(min(1,m.label_priority+(.08 if any(i in preferred for i in ids) else 0)),6)))
 selected=[]; used=set()
 for tid in [t.id for t in ts]:
  m=next((x for x in candidates if tid in x.topic_ids and x.id not in used),None)
  if m and len(selected)<memory_limit:selected.append(m);used.add(m.id)
 buckets=defaultdict(list)
 for m in candidates:
  if m.id not in used:buckets[m.primary_topic_id].append(m)
 while buckets and len(selected)<memory_limit:
  for tid in sorted(list(buckets)):
   if buckets[tid]:selected.append(buckets[tid].pop(0))
   if not buckets[tid]:del buckets[tid]
   if len(selected)>=memory_limit:break
 mids={m.id for m in selected}; relations=[r for r in snapshot.relations if (r.type=='contains' and r.source in allowed and r.target in mids) or (r.type=='co_occurs' and r.source in allowed and r.target in allowed)]
 return {'ok':True,'window':{'days':snapshot.days,'start':snapshot.window_start,'end':snapshot.window_end},'canonical_snapshot_key':snapshot.snapshot_key,'snapshot_key':projection_key(snapshot,topic_limit=topic_limit,memory_limit=memory_limit,topic_id=topic_id,include_memories=include_memories,preferences=p),'topics':[asdict(x) for x in ts],'memories':[asdict(x) for x in selected],'relations':[asdict(x) for x in relations],'presentation_defaults':{'visible_label_count':p.get('visible_label_count',3),'label_rotation_seconds':p.get('label_rotation_seconds',8),'default_days':p.get('default_days',30),'include_memory_labels':p.get('include_memory_labels',True),'client_owns_layout':True,'client_owns_animation':True}}
