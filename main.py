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
    page_title="전세계 고령화 지도",
    page_icon="🌍",
    layout="wide"
)

st.title("🌍 전세계 고령화 지도")

st.caption(
    "국가를 클릭하면 해당 국가의 연예인 정보를 확인할 수 있습니다."
)


# =========================================================
# 2. 데이터 주소
# =========================================================

KOREA_POPULATION_URL = (
    "https://raw.githubusercontent.com/greatsong/modudata/"
    "main/data/population_yearly.csv.gz"
)

KOREA_GEOJSON_URL = (
    "https://raw.githubusercontent.com/greatsong/modudata/"
    "main/data/boundaries/sigungu_kr.geojson"
)

WORLD_BANK_URL = (
    "https://api.worldbank.org/v2/country/all/"
    "indicator/SP.POP.65UP.TO.ZS"
    "?format=json&per_page=20000"
)

# Wikimedia / Wikidata
WIKIDATA_SPARQL_URL = (
    "https://query.wikidata.org/sparql"
)


# =========================================================
# 3. 전세계 고령화 데이터
# =========================================================

@st.cache_data
def load_world_data():

    response = requests.get(
        WORLD_BANK_URL,
        timeout=60
    )

    response.raise_for_status()

    data = response.json()

    if len(data) < 2:
        raise ValueError(
            "World Bank에서 데이터를 받지 못했습니다."
        )

    rows = data[1]

    result = []

    for row in rows:

        iso3 = row.get(
            "countryiso3code"
        )

        country_info = row.get(
            "country",
            {}
        )

        country_name = country_info.get(
            "value",
            ""
        )

        year = row.get(
            "date"
        )

        value = row.get(
            "value"
        )

        if not iso3:
            continue

        if not country_name:
            continue

        if value is None:
            continue

        result.append(
            {
                "ISO3": str(iso3).strip().upper(),
                "국가": country_name,
                "연도": int(year),
                "고령화율": float(value)
            }
        )

    world = pd.DataFrame(result)

    if world.empty:
        raise ValueError(
            "세계 인구 데이터를 만들지 못했습니다."
        )

    # ISO3 코드가 있는 자료만 사용
    world = world[
        world["ISO3"].str.len() == 3
    ].copy()

    # 국가별로 가장 최신 자료 사용
    world = (
        world
        .sort_values(
            ["ISO3", "연도"]
        )
        .groupby(
            "ISO3",
            as_index=False
        )
        .tail(1)
        .copy()
    )

    world["고령화율"] = (
        world["고령화율"]
        .round(2)
    )

    latest_year = int(
        world["연도"].max()
    )

    return world, latest_year


# =========================================================
# 4. 한국 인구 데이터
# =========================================================

@st.cache_data
def load_korea_population():

    response = requests.get(
        KOREA_POPULATION_URL,
        timeout=60
    )

    response.raise_for_status()

    data = gzip.decompress(
        response.content
    )

    # 행정구역 코드는 문자열로 읽는다.
    df = pd.read_csv(
        io.BytesIO(data),
        dtype={"코드": str}
    )

    return df


# =========================================================
# 5. 한국 GeoJSON
# =========================================================

@st.cache_data
def load_korea_geojson():

    response = requests.get(
        KOREA_GEOJSON_URL,
        timeout=60
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# 6. 한국 시군구별 고령화율 계산
# =========================================================

@st.cache_data
def make_korea_data(df):

    df = df.copy()

    df["코드"] = (
        df["코드"]
        .astype(str)
        .str.strip()
    )

    # 행정동 코드 앞 5자리 = 시군구 코드
    df["시군구코드"] = (
        df["코드"]
        .str[:5]
    )

    df["연도"] = pd.to_numeric(
        df["연도"],
        errors="coerce"
    )

    latest_year = int(
        df["연도"].max()
    )

    latest = df[
        df["연도"] == latest_year
    ].copy()

    # 모든 연령별 전체 인구 열
    age_columns = [
        col
        for col in latest.columns
        if col.startswith("계_")
    ]

    # 65세 이상 열
    elderly_columns = []

    for col in age_columns:

        age_text = (
            col
            .replace("계_", "")
            .strip()
        )

        if age_text == "100세 이상":

            elderly_columns.append(col)

        else:

            try:

                age = int(
                    age_text.replace(
                        "세",
                        ""
                    )
                )

                if age >= 65:
                    elderly_columns.append(col)

            except ValueError:
                pass

    if not elderly_columns:
        raise ValueError(
            "65세 이상 인구 열을 찾지 못했습니다."
        )

    # 숫자로 변환
    for col in age_columns:

        latest[col] = pd.to_numeric(
            latest[col],
            errors="coerce"
        ).fillna(0)

    latest["전체인구"] = (
        latest[age_columns]
        .sum(axis=1)
    )

    latest["65세이상인구"] = (
        latest[elderly_columns]
        .sum(axis=1)
    )

    # 시군구별 합계
    sigungu = (
        latest
        .groupby(
            "시군구코드",
            as_index=False
        )
        .agg(
            전체인구=(
                "전체인구",
                "sum"
            ),
            **{
                "65세이상인구": (
                    "65세이상인구",
                    "sum"
                )
            }
        )
    )

    sigungu = sigungu[
        sigungu["전체인구"] > 0
    ].copy()

    sigungu["고령화율"] = (
        sigungu["65세이상인구"]
        / sigungu["전체인구"]
        * 100
    )

    sigungu["고령화율"] = (
        sigungu["고령화율"]
        .round(2)
    )

    return sigungu, latest_year


# =========================================================
# 7. 한국 GeoJSON 지역 정보
# =========================================================

@st.cache_data
def get_korea_geo_info(geojson):

    rows = []

    for feature in geojson["features"]:

        properties = feature.get(
            "properties",
            {}
        )

        rows.append(
            {
                "시군구코드": str(
                    properties.get(
                        "코드",
                        ""
                    )
                ).strip(),

                "시군구": properties.get(
                    "시군구",
                    ""
                ),

                "시도": properties.get(
                    "시도",
                    ""
                )
            }
        )

    return pd.DataFrame(rows)


# =========================================================
# 8. 세계 지도 구간
# =========================================================

def classify_world_rate(rate):

    if rate < 7:
        return "7% 미만"

    elif rate < 14:
        return "7% 이상 ~ 14% 미만"

    elif rate < 21:
        return "14% 이상 ~ 21% 미만"

    elif rate < 28:
        return "21% 이상 ~ 28% 미만"

    else:
        return "28% 이상"


# =========================================================
# 9. 세계 지도 만들기
# =========================================================

def make_world_map(world):

    world = world.copy()

    world["구간"] = (
        world["고령화율"]
        .apply(
            classify_world_rate
        )
    )

    categories = [
        "7% 미만",
        "7% 이상 ~ 14% 미만",
        "14% 이상 ~ 21% 미만",
        "21% 이상 ~ 28% 미만",
        "28% 이상"
    ]

    colors = {

        "7% 미만":
            "#FFF7BC",

        "7% 이상 ~ 14% 미만":
            "#FEC44F",

        "14% 이상 ~ 21% 미만":
            "#FE9929",

        "21% 이상 ~ 28% 미만":
            "#EC7014",

        "28% 이상":
            "#CC4C02"
    }

    fig = go.Figure()

    for category in categories:

        selected = world[
            world["구간"] == category
        ]

        if selected.empty:
            continue

        # 국가코드를 customdata에도 넣는다.
        # 클릭했을 때 어떤 국가인지 알아내기 위해 사용한다.
        customdata = selected[
            [
                "ISO3",
                "국가",
                "고령화율",
                "연도"
            ]
        ].fillna("").values

        fig.add_trace(
            go.Choropleth(

                locations=selected["ISO3"],

                locationmode="ISO-3",

                z=[1] * len(selected),

                colorscale=[
                    [0, colors[category]],
                    [1, colors[category]]
                ],

                showscale=False,

                marker=dict(
                    line=dict(
                        color="white",
                        width=0.5
                    )
                ),

                name=category,

                customdata=customdata,

                hovertemplate=(
                    "<b>%{customdata[1]}</b><br>"
                    "65세 이상 인구 비율: "
                    "%{customdata[2]:.2f}%<br>"
                    "자료 연도: "
                    "%{customdata[3]}"
                    "<extra></extra>"
                )
            )
        )

    fig.update_geos(

        visible=False,

        projection_type="natural earth",

        showland=True,
        landcolor="white",

        showocean=True,
        oceancolor="white",

        showcountries=True,
        countrycolor="#cccccc"
    )

    fig.update_layout(

        height=650,

        margin=dict(
            l=0,
            r=0,
            t=10,
            b=10
        ),

        paper_bgcolor="white",
        plot_bgcolor="white",

        legend=dict(
            title="65세 이상 인구 비율",
            orientation="v",
            yanchor="top",
            y=0.98,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(255,255,255,0.9)",
            bordercolor="#cccccc",
            borderwidth=1
        )
    )

    return fig


# =========================================================
# 10. 클릭한 국가의 연예인 가져오기
# =========================================================

@st.cache_data(ttl=3600)
def get_celebrities(iso3):

    """
    Wikidata에서 해당 국가의 배우·가수·음악가 등의
    대표적인 인물과 이미지를 가져온다.

    ISO3 코드로 국가를 찾기 때문에
    국가 이름을 직접 검색하는 것보다 오류가 적다.
    """

    iso3 = str(iso3).upper().strip()

    # Wikidata SPARQL 쿼리
    #
    # P297 = ISO 3166-1 alpha-3
    # P27  = 국적
    # P18  = 대표 이미지
    # P106 = 직업
    #
    # 배우 / 가수 / 음악가 / 모델 등을 대상으로 한다.
    query = f"""
    SELECT ?person ?personLabel ?image WHERE {{

      ?country wdt:P297 "{iso3}".

      ?person wdt:P27 ?country.
      ?person wdt:P18 ?image.

      {{
        ?person wdt:P106 wd:Q33999.
      }}
      UNION
      {{
        ?person wdt:P106 wd:Q177220.
      }}
      UNION
      {{
        ?person wdt:P106 wd:Q639669.
      }}
      UNION
      {{
        ?person wdt:P106 wd:Q4610556.
      }}

      SERVICE wikibase:label {{
        bd:serviceParam
          wikibase:language "ko,en".
      }}
    }}

    LIMIT 8
    """

    headers = {
        "Accept": "application/sparql-results+json",
        "User-Agent": (
            "Streamlit-Aging-Map/1.0 "
            "(educational project)"
        )
    }

    try:

        response = requests.get(
            WIKIDATA_SPARQL_URL,
            params={
                "query": query,
                "format": "json"
            },
            headers=headers,
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

        results = data.get(
            "results",
            {}
        ).get(
            "bindings",
            []
        )

        people = []

        for item in results:

            name = (
                item
                .get("personLabel", {})
                .get("value")
            )

            image = (
                item
                .get("image", {})
                .get("value")
            )

            if not name or not image:
                continue

            people.append(
                {
                    "name": name,
                    "image": image
                }
            )

        # 중복 제거
        unique_people = []

        seen = set()

        for person in people:

            if person["name"] in seen:
                continue

            seen.add(
                person["name"]
            )

            unique_people.append(
                person
            )

        return unique_people

    except Exception:
        return []


# =========================================================
# 11. 연예인 사진 표시
# =========================================================

def show_celebrities(
    country_name,
    iso3
):

    st.divider()

    st.subheader(
        f"🎬 {country_name}의 연예인"
    )

    st.caption(
        "Wikidata에 대표 이미지가 등록된 배우·가수·음악가 등의 "
        "인물을 표시합니다."
    )

    people = get_celebrities(
        iso3
    )

    if not people:

        st.info(
            "이 국가에서 사용할 수 있는 연예인 이미지를 "
            "찾지 못했습니다."
        )

        return

    # 최대 8명
    people = people[:8]

    # 4명씩 두 줄에 표시
    columns = st.columns(4)

    for index, person in enumerate(people):

        with columns[index % 4]:

            st.image(
                person["image"],
                use_container_width=True
            )

            st.caption(
                person["name"]
            )


# =========================================================
# 12. 한국 지도
# =========================================================

def make_korea_map(
    sigungu,
    geojson
):

    geo_info = get_korea_geo_info(
        geojson
    )

    map_data = geo_info.merge(
        sigungu,
        on="시군구코드",
        how="left"
    )

    categories = [
        "19% 미만",
        "19% 이상 ~ 23% 미만",
        "23% 이상 ~ 28% 미만",
        "28% 이상 ~ 38% 미만",
        "38% 이상"
    ]

    colors = {

        "19% 미만":
            "#FFF7BC",

        "19% 이상 ~ 23% 미만":
            "#FEC44F",

        "23% 이상 ~ 28% 미만":
            "#FE9929",

        "28% 이상 ~ 38% 미만":
            "#EC7014",

        "38% 이상":
            "#CC4C02"
    }

    def classify_korea(rate):

        if pd.isna(rate):
            return None

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

    map_data["구간"] = (
        map_data["고령화율"]
        .apply(
            classify_korea
        )
    )

    fig = go.Figure()

    for category in categories:

        selected = map_data[
            map_data["구간"] == category
        ]

        if selected.empty:
            continue

        customdata = selected[
            [
                "시군구",
                "시도",
                "고령화율"
            ]
        ].fillna("").values

        fig.add_trace(
            go.Choropleth(

                geojson=geojson,

                featureidkey=(
                    "properties.코드"
                ),

                locations=selected[
                    "시군구코드"
                ],

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
                    "65세 이상 인구 비율: "
                    "%{customdata[2]:.2f}%"
                    "<extra></extra>"
                )
            )
        )

    fig.update_geos(
        fitbounds="locations",
        visible=False
    )

    fig.update_layout(

        height=700,

        margin=dict(
            l=0,
            r=0,
            t=10,
            b=10
        ),

        paper_bgcolor="white",
        plot_bgcolor="white",

        legend=dict(
            title="65세 이상 인구 비율",
            orientation="v",
            yanchor="top",
            y=0.98,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(255,255,255,0.9)",
            bordercolor="#cccccc",
            borderwidth=1
        )
    )

    return fig


# =========================================================
# 13. 데이터 불러오기
# =========================================================

try:

    world_df, world_year = (
        load_world_data()
    )

    korea_population = (
        load_korea_population()
    )

    korea_geojson = (
        load_korea_geojson()
    )

    korea_df, korea_year = (
        make_korea_data(
            korea_population
        )
    )

except Exception as e:

    st.error(
        "데이터를 불러오는 중 문제가 발생했습니다."
    )

    st.exception(e)

    st.stop()


# =========================================================
# 14. 전세계 지도
# =========================================================

st.header(
    "1. 전세계 고령화 지도"
)

st.write(
    "국가를 클릭하면 해당 국가의 연예인 사진이 아래에 나타납니다."
)

world_fig = make_world_map(
    world_df
)


# ---------------------------------------------------------
# 중요:
# on_select="rerun"을 사용하면
# 사용자가 지도에서 국가를 클릭했을 때
# Streamlit이 다시 실행되면서 클릭 정보를 받을 수 있다.
# ---------------------------------------------------------

world_event = st.plotly_chart(
    world_fig,

    use_container_width=True,

    key="world_aging_map",

    on_select="rerun",

    selection_mode="points",

    config={
        "displaylogo": False,
        "scrollZoom": False
    }
)


# =========================================================
# 15. 클릭한 국가 확인
# =========================================================

selected_iso3 = None
selected_country = None

try:

    points = world_event.selection.points

    if points:

        # 가장 최근에 선택한 국가
        point = points[0]

        customdata = point.get(
            "customdata"
        )

        if customdata:

            selected_iso3 = customdata[0]
            selected_country = customdata[1]

except Exception:
    pass


# =========================================================
# 16. 선택한 국가의 연예인 표시
# =========================================================

if selected_iso3 and selected_country:

    show_celebrities(
        selected_country,
        selected_iso3
    )

else:

    st.info(
        "👆 위 세계 지도에서 국가를 클릭해 보세요. "
        "선택한 국가의 연예인 사진이 이곳에 표시됩니다."
    )


# =========================================================
# 17. 세계 TOP / BOTTOM 10
# =========================================================

st.subheader(
    "전세계 국가별 고령화율"
)

world_ranking = (
    world_df
    .sort_values(
        "고령화율",
        ascending=False
    )
    .copy()
)

world_top10 = (
    world_ranking
    .head(10)
    [
        [
            "국가",
            "고령화율"
        ]
    ]
    .reset_index(drop=True)
)

world_top10.index += 1

world_bottom10 = (
    world_ranking
    .sort_values(
        "고령화율",
        ascending=True
    )
    .head(10)
    [
        [
            "국가",
            "고령화율"
        ]
    ]
    .reset_index(drop=True)
)

world_bottom10.index += 1

world_top10["고령화율"] = (
    world_top10["고령화율"]
    .map(
        lambda x:
        f"{x:.2f}%"
    )
)

world_bottom10["고령화율"] = (
    world_bottom10["고령화율"]
    .map(
        lambda x:
        f"{x:.2f}%"
    )
)

col1, col2 = st.columns(2)

with col1:

    st.markdown(
        "#### 고령화율 높은 국가 10개"
    )

    st.dataframe(
        world_top10,
        use_container_width=True,
        height=400
    )

with col2:

    st.markdown(
        "#### 고령화율 낮은 국가 10개"
    )

    st.dataframe(
        world_bottom10,
        use_container_width=True,
        height=400
    )


# =========================================================
# 18. 대한민국 시군구 지도
# =========================================================

st.header(
    "2. 대한민국 시군구 고령화 지도"
)

st.write(
    "한국은 읍·면·동 인구를 행정동 코드 앞 5자리 기준으로 "
    "시군구에 합산했습니다."
)

korea_fig = make_korea_map(
    korea_df,
    korea_geojson
)

st.plotly_chart(
    korea_fig,
    use_container_width=True,
    config={
        "displaylogo": False,
        "scrollZoom": False
    }
)

st.caption(
    f"한국 데이터 최신 연도: {korea_year}년"
)


# =========================================================
# 19. 한국 시군구 TOP / BOTTOM 10
# =========================================================

st.subheader(
    "대한민국 시군구별 고령화율"
)

korea_geo_info = (
    get_korea_geo_info(
        korea_geojson
    )
)

korea_ranking = korea_df.merge(
    korea_geo_info,
    on="시군구코드",
    how="left"
)

korea_ranking = korea_ranking[
    korea_ranking["고령화율"].notna()
].copy()


korea_top10 = (
    korea_ranking
    .sort_values(
        "고령화율",
        ascending=False
    )
    .head(10)
    [
        [
            "시도",
            "시군구",
            "고령화율"
        ]
    ]
    .reset_index(drop=True)
)

korea_top10.index += 1


korea_bottom10 = (
    korea_ranking
    .sort_values(
        "고령화율",
        ascending=True
    )
    .head(10)
    [
        [
            "시도",
            "시군구",
            "고령화율"
        ]
    ]
    .reset_index(drop=True)

korea_bottom10.index += 1


korea_top10["고령화율"] = (
    korea_top10["고령화율"]
    .map(
        lambda x:
        f"{x:.2f}%"
    )
)

korea_bottom10["고령화율"] = (
    korea_bottom10["고령화율"]
    .map(
        lambda x:
        f"{x:.2f}%"
    )
)


col1, col2 = st.columns(2)

with col1:

    st.markdown(
        "#### 고령화율 높은 시군구 10개"
    )

    st.dataframe(
        korea_top10,
        use_container_width=True,
        height=400
    )

with col2:

    st.markdown(
        "#### 고령화율 낮은 시군구 10개"
    )

    st.dataframe(
        korea_bottom10,
        use_container_width=True,
        height=400
    )


# =========================================================
# 20. 데이터 출처
# =========================================================

st.divider()

st.subheader(
    "데이터 출처"
)

st.caption(
    "세계 고령화 데이터: World Bank "
    "Population ages 65 and above (% of total population), "
    "UN World Population Prospects 기반"
)

st.caption(
    "한국 인구 및 시군구 경계: "
    "greatsong/modudata"
)

st.caption(
    "연예인 인물 및 이미지: "
    "Wikidata / Wikimedia Commons"
)
