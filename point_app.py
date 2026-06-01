"""
TONYAポイント付与計算（Streamlit）

起動: streamlit run point_app.py
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from point_logic import (
    CampaignConfig,
    CampaignRounding,
    LineInput,
    OrderConfig,
    RANK_RATES,
    TaxExMethod,
    calculate_order,
)

st.set_page_config(
    page_title="TONYAポイント付与計算",
    page_icon="🎁",
    layout="wide",
)

TAX_METHOD_LABELS = {
    TaxExMethod.UNIT_TAX_ROUND: "単価ごと税額四捨五入→合算（レジ明細・推奨）",
    TaxExMethod.TAX_ROUND: "行合計の税込から税額四捨五入",
    TaxExMethod.DIVIDE_FLOOR: "税込÷(1+税率) を切り捨て（単純除算）",
    TaxExMethod.TAX_FLOOR: "税込−消費税（切り捨て）",
}

DEFAULT_LINES = pd.DataFrame(
    [
        {
            "明細名": "ギフト商品",
            "税込単価": 3576,
            "数量": 6,
            "税率": 0.08,
            "バーゲン品": False,
            "商品外売上": False,
            "キャンペーン対象": True,
        },
        {
            "明細名": "送料",
            "税込単価": 550,
            "数量": 6,
            "税率": 0.10,
            "バーゲン品": False,
            "商品外売上": True,
            "キャンペーン対象": False,
        },
    ]
)


def _init_session() -> None:
    if "lines_df" not in st.session_state:
        st.session_state.lines_df = DEFAULT_LINES.copy()


def _df_to_lines(df: pd.DataFrame) -> list[LineInput]:
    lines: list[LineInput] = []
    for _, row in df.iterrows():
        if int(row.get("数量", 0) or 0) <= 0:
            continue
        lines.append(
            LineInput(
                label=str(row.get("明細名", "明細")),
                tax_in_unit=int(row.get("税込単価", 0) or 0),
                quantity=int(row.get("数量", 1) or 1),
                tax_rate=float(row.get("税率", 0.10) or 0.10),
                is_bargain=bool(row.get("バーゲン品", False)),
                is_non_product=bool(row.get("商品外売上", False)),
                campaign_target=bool(row.get("キャンペーン対象", False)),
            )
        )
    return lines


def main() -> None:
    _init_session()
    st.title("TONYAポイント付与計算")
    st.caption(
        "会員ランクの付与率・明細（行）単位の切り捨て・キャンペーン倍率を試算します。"
        " 送料などはキャンペーン対象にしないでください（通常ポイントのみ）。"
    )

    with st.sidebar:
        st.header("会員・受注")
        rank = st.selectbox("会員ランク", list(RANK_RATES.keys()), index=3)
        points_used = st.number_input("利用ポイント（円相当）", min_value=0, value=0, step=1)
        point_basis = st.radio(
            "ポイント利用の按分基準",
            options=["tax_in", "tax_ex"],
            format_func=lambda x: "税込合計" if x == "tax_in" else "税抜合計",
        )

        st.header("税抜の出し方")
        tax_method_key = st.selectbox(
            "計算方法",
            options=list(TAX_METHOD_LABELS.keys()),
            format_func=lambda m: TAX_METHOD_LABELS[m],
            index=0,
        )

        st.header("ポイントアップキャンペーン")
        campaign_enabled = st.checkbox("キャンペーンを適用", value=True)
        campaign_name = st.text_input("キャンペーン名", value="ギフト5倍（2026年6月）")
        campaign_multiplier = st.number_input(
            "倍率（通常ptに対して）",
            min_value=1.0,
            max_value=20.0,
            value=5.0,
            step=0.5,
        )
        rounding_label = st.selectbox(
            "倍率適用後の端数",
            ["切り上げ", "切り捨て", "端数処理なし"],
            index=0,
        )
        rounding_map = {
            "切り上げ": CampaignRounding.CEIL,
            "切り捨て": CampaignRounding.FLOOR,
            "端数処理なし": CampaignRounding.NONE,
        }

        st.divider()
        if st.button("例：ギフト×6＋送料×6（ダイヤ）", use_container_width=True):
            st.session_state.lines_df = DEFAULT_LINES.copy()

    st.subheader("明細入力")
    st.info(
        "各行は **税込単価×数量** の行合計で税抜・ポイントを計算します（レジの1明細行と同じ考え方）。"
        " **キャンペーン対象** にチェックした行だけ倍率がかかります。"
    )

    edited = st.data_editor(
        st.session_state.lines_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "明細名": st.column_config.TextColumn("明細名", width="medium"),
            "税込単価": st.column_config.NumberColumn("税込単価（円）", min_value=0, step=1),
            "数量": st.column_config.NumberColumn("数量", min_value=0, step=1),
            "税率": st.column_config.SelectboxColumn(
                "税率",
                options=[0.08, 0.10],
                help="8%=軽減税率、10%=標準",
            ),
            "バーゲン品": st.column_config.CheckboxColumn("バーゲン品", help="100%値引相当→付与0"),
            "商品外売上": st.column_config.CheckboxColumn(
                "商品外売上", help="送料など（通常ptのみ）"
            ),
            "キャンペーン対象": st.column_config.CheckboxColumn(
                "キャンペーン対象",
                help="オンにした行のみ倍率適用。送料はオフ推奨",
            ),
        },
        hide_index=True,
        key="lines_editor",
    )
    st.session_state.lines_df = edited

    lines = _df_to_lines(edited)
    if not lines:
        st.warning("有効な明細がありません（数量1以上）。")
        return

    order = OrderConfig(
        rank_rate=RANK_RATES[rank],
        tax_ex_method=tax_method_key,
        points_used=int(points_used),
        point_usage_basis=point_basis,  # type: ignore[arg-type]
    )
    campaign = CampaignConfig(
        enabled=campaign_enabled,
        name=campaign_name,
        multiplier=float(campaign_multiplier),
        rounding=rounding_map[rounding_label],
    )

    results, total_pts, memo = calculate_order(lines, order, campaign)

    st.subheader("計算結果")
    result_df = pd.DataFrame(
        [
            {
                "明細": r.label,
                "税込行計": r.tax_in_line,
                "税抜行計": r.tax_ex_line,
                "通常pt": r.normal_points,
                "付与pt": r.final_points,
                "キャンペーン": "○" if r.campaign_applied else "",
                "備考": r.note,
            }
            for r in results
        ]
    )
    st.dataframe(result_df, use_container_width=True, hide_index=True)

    c1, c2, c3 = st.columns(3)
    c1.metric("合計付与ポイント", f"{total_pts:,} pt")
    c2.metric("会員付与率", f"{order.rank_rate * 100:g}%")
    c3.metric("キャンペーン", campaign_name if campaign.enabled else "なし")

    if memo:
        st.warning(memo)

    with st.expander("計算ルール（このツールの前提）"):
        st.markdown(
            """
- **付与率**: ホワイト・シルバー 1% / ゴールド 2% / ダイヤモンド 3%
- **通常ポイント**: 明細行の税抜合計 × 付与率 → **切り捨て**
- **バーゲン品**: 付与0（チェックで指定）
- **キャンペーン**: 対象行のみ「通常pt × 倍率」→ 指定の端数処理（既定は切り上げ）
- **送料**: キャンペーン対象にしない → 通常ポイントのみ
- **ポイント利用**: 税込または税抜合計に対し残比率で各明細の付与を按分（切り捨て）
- **最低100円**: 税抜合計が100円未満のとき警告（付与0として表示）

レジ実績と1ptずれる場合は、税抜の出し方（サイドバー）や明細の行の分け方を変えてください。
            """
        )


if __name__ == "__main__":
    main()
