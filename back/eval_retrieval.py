# -*- coding: utf-8 -*-
"""
检索质量评估脚本
自动计算 HitRate@K，评估本地知识库检索效果
"""
from knowledge_base import search_with_scores

# 测试用例：query + 预期相关文档关键词
# 每个用例对应知识库中的一条具体谣言
TEST_CASES = [
    {"query": "骨头汤能补钙吗", "expected_keywords": ["骨头汤", "补钙"]},
    {"query": "微波炉加热食物会致癌吗", "expected_keywords": ["微波炉", "致癌"]},
    {"query": "隔夜菜亚硝酸盐超标", "expected_keywords": ["隔夜菜", "亚硝酸盐"]},
    {"query": "黄鳝是喂避孕药长大的吗", "expected_keywords": ["黄鳝", "避孕药"]},
    {"query": "吃胶原蛋白可以美容抗衰老吗", "expected_keywords": ["胶原蛋白", "美容"]},
    {"query": "酸性体质会致癌吗", "expected_keywords": ["酸性体质", "pH值"]},
    {"query": "手机辐射致癌", "expected_keywords": ["手机", "辐射", "致癌"]},
    {"query": "WiFi信号对人体有害吗", "expected_keywords": ["WiFi", "辐射", "非电离"]},
    {"query": "用肥皂洗手比清水伤手", "expected_keywords": ["肥皂", "洗手"]},
    {"query": "掰手指关节会得关节炎吗", "expected_keywords": ["掰手指", "关节炎"]},
    {"query": "仙人掌能防电脑辐射吗", "expected_keywords": ["仙人掌", "辐射"]},
    {"query": "手机NFC会被盗刷吗", "expected_keywords": ["NFC", "盗刷"]},
    {"query": "量子鞋垫能治病吗", "expected_keywords": ["量子", "智商税"]},
    {"query": "医保余额年底清零", "expected_keywords": ["医保", "清零"]},
    {"query": "住院超过15天医保不报销", "expected_keywords": ["住院", "15天", "医保"]},
    {"query": "海南封关就是封岛吗", "expected_keywords": ["海南", "封关", "封岛"]},
    {"query": "乡村振兴补贴点链接领取", "expected_keywords": ["补贴", "诈骗", "链接"]},
    {"query": "人贩子偷小孩是真的吗", "expected_keywords": ["人贩子", "博流量"]},
    {"query": "肯德基六翅四腿鸡", "expected_keywords": ["肯德基", "六翅", "PS伪造"]},
    {"query": "冷冻水饺没有营养", "expected_keywords": ["冷冻", "营养", "速冻"]},
    {"query": "辣条是尸油做的", "expected_keywords": ["辣条", "尸油", "谣言"]},
]


def evaluate(top_k=3, score_threshold=0.3):
    """
    评估检索效果
    :param top_k: 取前 K 个结果
    :param score_threshold: 最低分数阈值（低于此分数视为未命中）
    :return: hit_rate
    """
    hit_count = 0
    miss_cases = []

    for case in TEST_CASES:
        results = search_with_scores(case["query"], top_k=top_k)
        # 过滤低于阈值的结果
        filtered = [(doc, score) for doc, score in results if score >= score_threshold]
        # 检查返回的文档里是否包含至少一个预期关键词
        hit = False
        for doc, score in filtered:
            if any(kw in doc.page_content for kw in case["expected_keywords"]):
                hit = True
                break
        if hit:
            hit_count += 1
        else:
            # 记录未命中的用例，便于分析
            top_score = results[0][1] if results else 0
            top_preview = results[0][0].page_content[:30].replace('\n', ' ') if results else "无结果"
            miss_cases.append({
                "query": case["query"],
                "top_score": round(top_score, 4),
                "top_preview": top_preview,
            })

    hit_rate = hit_count / len(TEST_CASES)
    print(f"\n{'='*60}")
    print(f"📊 检索质量评估 (HitRate@{top_k}, 阈值={score_threshold})")
    print(f"{'='*60}")
    print(f"命中率: {hit_rate:.2%} ({hit_count}/{len(TEST_CASES)})")

    if miss_cases:
        print(f"\n❌ 未命中的用例 ({len(miss_cases)} 个):")
        for c in miss_cases:
            print(f"  - {c['query']}")
            print(f"    最高分: {c['top_score']} | 顶部内容: {c['top_preview']}...")
    else:
        print(f"\n✅ 全部命中！")

    print(f"{'='*60}\n")
    return hit_rate


if __name__ == "__main__":
    # 评估不同阈值下的效果
    for threshold in [0.3, 0.4, 0.5, 0.6]:
        evaluate(top_k=3, score_threshold=threshold)
