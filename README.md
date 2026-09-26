# 涉外语言人才动态调度

约定涉外语言人才、活动需求、派遣和反馈的数据结构。

## 领域资料

仓库中的 `contracts/context.schema.json` 描述基础资料格式，`fixtures/context.json` 给出可公开使用的示例。代码库只负责读取与校验这些资料，业务服务可沿用相同标识和版本约定。

当前资料反映的事实包括：

- 人才库包含专家、翻译人员和志愿者
- 五所高校参与长期合作
- 青少年志愿服务需要单独管理

## 本地校验

运行项目自带测试即可确认样例资料可读取，且领域标识与版本字段完整。所有示例均为虚构数据，不含真实个人信息、账号或访问凭据。

## 调度后台

在领域资料之上，`src/` 提供语言服务调度后台：

- `models.py` — 人员侧维护语种方向、能力证明、服务类型、可用时段、所属单位、保密级别和历史反馈；活动侧记录场景、地点、时区、敏感程度与候补规则；未成年志愿者须同时持有监护人与学校授权，且不得参与成人/敏感议题
- `pool.py` — 人才库只通过 `record_service`（真实完成的服务）写入反馈；`purge` 定期清出过期证书、失效授权与失效名单
- `scheduling.py` — 逐岗资格校验并给出通过/否决理由，检测时间、地点、职责三类冲突，按候补规则排序人选
- `dispatch.py` — 多人同时派单与竞态接受（先到先生效，其余拒绝留痕）；缺席、改期、临时小语种嘉宾都会触发影响重算；每次邀约/接受/拒绝/撤销写入审计日志
- `roster.py` — 生成最终值守表：逐岗说明为何由该人员承担，整体校验无冲突并暴露空缺岗位
- `seed.py` + `fixtures/seed.json` — 基于五所合作高校与专家/翻译/志愿者分类的虚构样例

```bash
python -m pytest        # 运行全部测试
```

```python
from pathlib import Path
from src.seed import load_seed
from src.roster import build_roster

pool, dispatcher = load_seed(Path("fixtures/seed.json"))
for post_id in dispatcher.posts:
    for offer in dispatcher.dispatch(post_id):
        dispatcher.respond(offer.assignment_id, accept=True)
        break
roster = build_roster(dispatcher)  # entries / conflicts / unfilled_posts
```
