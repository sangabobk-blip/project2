
# main.py

import io
import gzip
import requests
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# =========================================================
# 1. 기본 설정
# =========================================================

st.set_page_config(
    page_title="전국 고령화 지도",
    page_icon="🗺️",
    layout="wide"
)

st.title("전국 시군구 고령화 지도")
st.caption("65세 이상 인구 비율을 기준으로 시군구별 고령화 정도를 나타낸 지도")


# =========================================================
# 2. 데이터 주소
# =========================================================

POPULATION_URL = (
    "https://raw.githubusercontent.com/greatsong/modudata/"
    "main/data/population_yearly.csv.gz"
)

GEOJSON_URL = (
    "https://raw.githubusercontent.com/greatsong/modudata/"
    "main/data/boundaries/sigungu_kr.geojson"
)


# =========================================================
# 3. 데이터 불러오기
# =========================================================

@st.cache_data
def load_population_data():
    """인구 데이터를 내려받아 판다스 데이터프레임으로 읽는다."""

    response = requests.get(POPULATION_URL, timeout=60)
    response.raise_for_status()

    # .gz 파일이므로 압축을 풀어서 읽는다.
    data = gzip.decompress(response.content)

    # 코드가 숫자로 바뀌면 앞자리 0이 사라질 수 있으므로
    # 반드시 문자열로 읽는다.
    df = pd.read_csv(
        io.BytesIO(data),
        dtype={"코드": str}
    )

    return df


@st.cache_data
def load_geojson():
    """시군구 경계 GeoJSON을 불러온다."""

    response = requests.get(GEOJSON_URL, timeout=60)
    response.raise_for_status()

    return response.json()


# =========================================================
# 4. 시군구별 고령화율 계산
# =========================================================

@st.cache_data
def make_sigungu_data(df):
    """
    읍·면·동 인구를 시군구 단위로 합친다.

    시군구 코드는 행정동 코드의 앞 5자리이다.
    """

    # 코드가 문자열인지 다시 확인한다.
    df = df.copy()
    df["코드"] = df["코드"].astype(str).str.strip()

    # 행정동 코드 앞 5자리가 시군구 코드
    df["시군구코드"] = df["코드"].str[:5]

    # 연도는 숫자로 변환
    df["연도"] = pd.to_numeric(df["연도"], errors="coerce")

    # 가장 최신 연도 선택
    latest_year = int(df["연도"].max())

    latest = df[df["연도"] == latest_year].copy()

    # -----------------------------------------------------
    # 나이별 '계_' 열 찾기
    # 예:
    # 계_0세, 계_1세, ... 계_65세, ... 계_100세 이상
    # -----------------------------------------------------

    age_columns = [
        col
        for col in latest.columns
        if col.startswith("계_")
    ]

    # 65세 이상에 해당하는 열만 선택
    elderly_columns = []

    for col in age_columns:
        age_text = col.replace("계_", "").strip()

        if age_text == "100세 이상":
            elderly_columns.append(col)

        else:
            try:
                age = int(age_text.replace("세", ""))

                if age >= 65:
                    elderly_columns.append(col)

            except ValueError:
                # 나이 형식이 아닌 열은 무시
                pass

    if not elderly_columns:
        raise ValueError("65세 이상 인구 열을 찾지 못했습니다.")

    # 숫자로 변환
    for col in age_columns:
        latest[col] = pd.to_numeric(
            latest[col],
            errors="coerce"
        ).fillna(0)

    # 전체 인구 = 모든 '계_' 나이별 인구 합계
    latest["전체인구"] = latest[age_columns].sum(axis=1)

    # 65세 이상 인구
    latest["65세이상인구"] = latest[elderly_columns].sum(axis=1)

    # -----------------------------------------------------
    # 시군구별 합계
    # -----------------------------------------------------

    sigungu = (
        latest
        .groupby("시군구코드", as_index=False)
        .agg(
            전체인구=("전체인구", "sum"),
            **{"65세이상인구": ("65세이상인구", "sum")}
        )
    )

    # 고령화율 계산
    sigungu["고령화율"] = (
        sigungu["65세이상인구"]
        / sigungu["전체인구"]
        * 100
    )

    # 0으로 나누는 경우 제거
    sigungu = sigungu[
        sigungu["전체인구"] > 0
    ].copy()

    # 표시용 소수점
    sigungu["고령화율"] = sigungu["고령화율"].round(2)

    return sigungu, latest_year


# =========================================================
# 5. GeoJSON의 속성 확인
# =========================================================

@st.cache_data
def get_geojson_info(geojson):
    """
    GeoJSON에서 시군구 코드, 시군구 이름, 시도 이름을 가져온다.
    """

    rows = []

    for feature in geojson["features"]:
        properties = feature.get("properties", {})

        code = str(properties.get("코드", "")).strip()

        rows.append(
            {
                "시군구코드": code,
                "시군구": properties.get("시군구", ""),
                "시도": properties.get("시도", "")
            }
        )

    return pd.DataFrame(rows)


# =========================================================
# 6. 단계구분용 구간 만들기
# =========================================================

def classify_rate(rate):
    """
    고령화율을 5개 구간으로 나눈다.

    19% 미만
    19% 이상 ~ 23% 미만
    23% 이상 ~ 28% 미만
    28% 이상 ~ 38% 미만
    38% 이상
    """

    if rate < 19:
        return "19% 미만"

    elif rate < 23:
        return "19% 이상 ~ 23% 미만"

    elif rate < 28:
        return "23% 이상 ~ 28% 미만"

    elif rate < 38:
        return "28% 이상 ~ 38% 미만"

    else:
        return "38% 이상"


# =========================================================
# 7. 지도 만들기
# =========================================================

def make_map(sigungu, geojson):
    """시군구별 고령화율 단계구분도를 만든다."""

    # GeoJSON 속성에서 지역 이름을 가져온다.
    geo_info = get_geojson_info(geojson)

    # 지도 데이터와 지역 정보를 코드로 연결한다.
    map_data = geo_info.merge(
        sigungu,
        on="시군구코드",
        how="left"
    )

    # 고령화율을 5단계로 분류
    map_data["구간"] = map_data["고령화율"].apply(
        lambda x: classify_rate(x)
        if pd.notna(x)
        else "자료 없음"
    )

    # 단계 순서
    categories = [
        "19% 미만",
        "19% 이상 ~ 23% 미만",
        "23% 이상 ~ 28% 미만",
        "28% 이상 ~ 38% 미만",
        "38% 이상"
    ]

    # 낮은 단계에서 높은 단계로 갈수록 진하게
    # 원하는 경우 여기의 색상만 바꾸면 된다.
    colors = {
        "19% 미만": "#FFF7BC",
        "19% 이상 ~ 23% 미만": "#FEC44F",
        "23% 이상 ~ 28% 미만": "#FE9929",
        "28% 이상 ~ 38% 미만": "#EC7014",
        "38% 이상": "#CC4C02"
    }

    fig = go.Figure()

    # -----------------------------------------------------
    # 각 구간을 하나의 지도 레이어로 만들어
    # 범례에 5개 구간이 표시되도록 한다.
    # -----------------------------------------------------

    for category in categories:

        selected = map_data[
            map_data["구간"] == category
        ]

        if selected.empty:
            continue

        # 마우스를 올렸을 때 보여줄 정보
        customdata = selected[
            ["시군구", "시도", "고령화율"]
        ].fillna("").values

        fig.add_trace(
            go.Choropleth(
                geojson=geojson,
                featureidkey="properties.코드",

                locations=selected["시군구코드"],

                # 단계구분도에서는 같은 구간이 모두 같은 색을 사용한다.
                z=[1] * len(selected),

                colorscale=[
                    [0, colors[category]],
                    [1, colors[category]]
                ],

                showscale=False,

                marker=dict(
                    line=dict(
                        color="white",
                        width=0.7
                    )
                ),

                name=category,

                customdata=customdata,

                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "시도: %{customdata[1]}<br>"
                    "고령화율: %{customdata[2]:.2f}%"
                    "<extra></extra>"
                )
            )
        )

    # -----------------------------------------------------
    # 지도 설정
    # -----------------------------------------------------

    fig.update_geos(
        fitbounds="locations",
        visible=False,
        bgcolor="rgba(0,0,0,0)"
    )

    fig.update_layout(
        height=750,

        # 배경 지도 타일을 사용하지 않는다.
        paper_bgcolor="white",
        plot_bgcolor="white",

        margin=dict(
            l=0,
            r=0,
            t=10,
            b=10
        ),

        legend=dict(
            title="고령화율",
            orientation="v",
            yanchor="top",
            y=0.98,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#cccccc",
            borderwidth=1
        )
    )

    return fig, map_data


# =========================================================
# 8. 데이터 불러오기
# =========================================================

try:
    population_df = load_population_data()
    geojson = load_geojson()

    sigungu_df, latest_year = make_sigungu_data(
        population_df
    )

except Exception as e:
    st.error("데이터를 불러오는 중 문제가 발생했습니다.")
    st.exception(e)
    st.stop()


# =========================================================
# 9. 지도 데이터와 GeoJSON 연결
# =========================================================

fig, map_data = make_map(
    sigungu_df,
    geojson
)


# =========================================================
# 10. 지도 출력
# =========================================================

st.subheader(f"{latest_year}년 전국 시군구 고령화 지도")

st.plotly_chart(
    fig,
    use_container_width=True,
    config={
        "displaylogo": False,
        "scrollZoom": False
    }
)


# =========================================================
# 11. 지도에 연결되지 않은 지역 확인
# =========================================================

matched = map_data["고령화율"].notna().sum()
total_regions = len(map_data)

st.caption(
    f"지도에 표시된 시군구: {matched}개 / "
    f"전체 경계: {total_regions}개"
)


# =========================================================
# 12. 고령화율 높은 지역 / 낮은 지역
# =========================================================

st.subheader("고령화율 비교")

# 이름과 시도 정보를 붙인 데이터
ranking = sigungu_df.merge(
    get_geojson_info(geojson),
    on="시군구코드",
    how="left"
)

ranking = ranking[
    ranking["고령화율"].notna()
].copy()


# 높은 지역 10개
top10 = (
    ranking
    .sort_values("고령화율", ascending=False)
    .head(10)
    .reset_index(drop=True)
)

top10.index = top10.index + 1

top10_table = top10[
    ["시도", "시군구", "고령화율"]
].copy()

top10_table.columns = [
    "시도",
    "시군구",
    "고령화율 (%)"
]

top10_table["고령화율 (%)"] = (
    top10_table["고령화율 (%)"]
    .map(lambda x: f"{x:.2f}%")
)


# 낮은 지역 10개
bottom10 = (
    ranking
    .sort_values("고령화율", ascending=True)
    .head(10)
    .reset_index(drop=True)
)

bottom10.index = bottom10.index + 1

bottom10_table = bottom10[
    ["시도", "시군구", "고령화율"]
].copy()

bottom10_table.columns = [
    "시도",
    "시군구",
    "고령화율 (%)"
]

bottom10_table["고령화율 (%)"] = (
    bottom10_table["고령화율 (%)"]
    .map(lambda x: f"{x:.2f}%")
)


# =========================================================
# 13. 두 표를 나란히 표시
# =========================================================

col1, col2 = st.columns(2)

with col1:
    st.markdown("#### 고령화율 높은 지역 10개")
    st.dataframe(
        top10_table,
        use_container_width=True,
        height=430
    )

with col2:
    st.markdown("#### 고령화율 낮은 지역 10개")
    st.dataframe(
        bottom10_table,
        use_container_width=True,
        height=430
    )


# =========================================================
# 14. 데이터 기준 안내
# =========================================================

st.caption(
    "고령화율 = 65세 이상 인구 ÷ 전체 인구 × 100. "
    "읍·면·동 인구를 행정동 코드 앞 5자리 기준으로 시군구에 합산하여 계산했다."
)
