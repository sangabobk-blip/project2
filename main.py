import gzip
import io

import pandas as pd
import requests
import streamlit as st
import plotly.graph_objects as go


# ============================================================
# 1. 페이지 설정
# ============================================================

st.set_page_config(
    page_title="세계·한국 고령화 지도",
    page_icon="🌍",
    layout="wide"
)

st.title("🌍 세계·한국 고령화 지도")

st.write(
    "세계 각국의 고령화율과 한국 시군구별 고령화율을 "
    "지도에서 확인할 수 있습니다."
)


# ============================================================
# 2. 데이터 주소
# ============================================================

POPULATION_URL = (
    "https://raw.githubusercontent.com/greatsong/modudata/main/"
    "data/population_yearly.csv.gz"
)

GEOJSON_URL = (
    "https://raw.githubusercontent.com/greatsong/modudata/main/"
    "data/boundaries/sigungu_kr.geojson"
)

WORLD_BANK_URL = (
    "https://api.worldbank.org/v2/country/all/indicator/"
    "SP.POP.65UP.TO.ZS"
    "?format=json&per_page=20000"
)


# ============================================================
# 3. 한국 인구 데이터 불러오기
# ============================================================

@st.cache_data
def load_population_data():

    response = requests.get(
        POPULATION_URL,
        timeout=60
    )

    response.raise_for_status()

    with gzip.GzipFile(
        fileobj=io.BytesIO(response.content)
    ) as gz:

        df = pd.read_csv(
            gz,
            dtype={"코드": str}
        )

    # 열 이름 정리
    df.columns = (
        df.columns
        .astype(str)
        .str.replace("\ufeff", "", regex=False)
        .str.strip()
    )

    return df


# ============================================================
# 4. 한국 지도 GeoJSON 불러오기
# ============================================================

@st.cache_data
def load_geojson():

    response = requests.get(
        GEOJSON_URL,
        timeout=60
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# 5. 세계 데이터 불러오기
# ============================================================

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

        year = row.get("date")
        value = row.get("value")

        if (
            not iso3
            or not country_name
            or value is None
        ):
            continue

        try:
            year = int(year)
            value = float(value)
        except (ValueError, TypeError):
            continue

        result.append(
            {
                "ISO3": str(iso3).strip().upper(),
                "국가": country_name,
                "연도": year,
                "고령화율": value
            }
        )

    world = pd.DataFrame(result)

    if world.empty:
        raise ValueError(
            "세계 인구 데이터를 만들지 못했습니다."
        )

    world = world[
        world["ISO3"].str.len() == 3
    ].copy()

    # 국가별 가장 최근 연도 자료만 사용
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


# ============================================================
# 6. 세계 지도 만들기
# ============================================================

def make_world_map(world):

    def get_level(value):

        if value < 7:
            return 0

        elif value < 14:
            return 1

        elif value < 21:
            return 2

        elif value < 28:
            return 3

        else:
            return 4

    selected = world.copy()

    selected["등급"] = (
        selected["고령화율"]
        .apply(get_level)
    )

    colors = [
        "#f7fbff",
        "#c6dbef",
        "#6baed6",
        "#2171b5",
        "#08306b"
    ]

    labels = [
        "7% 미만",
        "7% 이상 ~ 14% 미만",
        "14% 이상 ~ 21% 미만",
        "21% 이상 ~ 28% 미만",
        "28% 이상"
    ]

    fig = go.Figure()

    for level in range(5):

        part = selected[
            selected["등급"] == level
        ].copy()

        if part.empty:
            continue

        customdata = (
            part[
                [
                    "ISO3",
                    "국가",
                    "고령화율",
                    "연도"
                ]
            ]
            .fillna("")
            .values
        )

        fig.add_trace(
            go.Choropleth(
                locations=part["ISO3"],
                z=[level] * len(part),
                locationmode="ISO-3",

                colorscale=[
                    [0, colors[level]],
                    [1, colors[level]]
                ],

                showscale=False,

                customdata=customdata,

                hovertemplate=(
                    "<b>%{customdata[1]}</b><br>"
                    "고령화율: %{customdata[2]}%<br>"
                    "자료 연도: %{customdata[3]}"
                    "<extra></extra>"
                ),

                name=labels[level]
            )
        )

    fig.update_layout(

        title="세계 65세 이상 인구 비율",

        geo=dict(
            showframe=False,
            showcoastlines=True,
            showland=True,
            showcountries=True,
            projection_type="natural earth",
            bgcolor="rgba(0,0,0,0)"
        ),

        margin=dict(
            l=0,
            r=0,
            t=60,
            b=0
        ),

        legend=dict(
            title="고령화율",
            orientation="h",
            yanchor="bottom",
            y=0.01,
            xanchor="center",
            x=0.5
        )
    )

    return fig


# ============================================================
# 7. 선택한 나라의 연예인 가져오기
# ============================================================

@st.cache_data(ttl=3600)
def get_celebrities(iso3):

    query = f"""
    SELECT ?person ?personLabel ?image WHERE {{

      ?country wdt:P297 "{iso3}" .

      ?person wdt:P27 ?country .

      ?person wdt:P18 ?image .

      {{
        ?person wdt:P106 wd:Q33999 .
      }}
      UNION
      {{
        ?person wdt:P106 wd:Q177220 .
      }}
      UNION
      {{
        ?person wdt:P106 wd:Q639669 .
      }}
      UNION
      {{
        ?person wdt:P106 wd:Q4610556 .
      }}

      SERVICE wikibase:label {{
        bd:serviceParam
        wikibase:language "ko,en" .
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

    response = requests.get(
        "https://query.wikidata.org/sparql",
        params={
            "query": query,
            "format": "json"
        },
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    bindings = (
        data
        .get("results", {})
        .get("bindings", [])
    )

    results = []

    for item in bindings:

        name = (
            item
            .get("personLabel", {})
            .get("value", "")
        )

        image = (
            item
            .get("image", {})
            .get("value", "")
        )

        if name and image:

            results.append(
                {
                    "name": name,
                    "image": image
                }
            )

    return results


# ============================================================
# 8. 한국 데이터 가공
# ============================================================

@st.cache_data
def make_korea_data(df):

    df = df.copy()

    # --------------------------------------------------------
    # 열 이름 정리
    # --------------------------------------------------------

    df.columns = (
        df.columns
        .astype(str)
        .str.replace(
            "\ufeff",
            "",
            regex=False
        )
        .str.strip()
    )

    # --------------------------------------------------------
    # 연도 열 찾기
    # --------------------------------------------------------

    year_candidates = [
        "year",
        "연도",
        "년도",
        "기준연도",
        "기준년도"
    ]

    year_column = None

    for column in year_candidates:

        if column in df.columns:
            year_column = column
            break

    # 연도 열을 못 찾으면 자동 탐색
    if year_column is None:

        for column in df.columns:

            try:

                values = pd.to_numeric(
                    df[column],
                    errors="coerce"
                )

                valid_values = (
                    values.dropna()
                )

                if len(valid_values) == 0:
                    continue

                year_ratio = (
                    valid_values
                    .between(2000, 2100)
                    .mean()
                )

                if year_ratio > 0.8:

                    year_column = column
                    break

            except Exception:
                continue

    # 그래도 못 찾은 경우
    if year_column is None:

        raise ValueError(
            "인구 데이터에서 연도 열을 찾지 못했습니다. "
            f"현재 열: {list(df.columns)}"
        )

    # 연도 숫자 변환
    df[year_column] = pd.to_numeric(
        df[year_column],
        errors="coerce"
    )

    df = df.dropna(
        subset=[year_column]
    )

    # --------------------------------------------------------
    # 필요한 지역 열 확인
    # --------------------------------------------------------

    required_columns = [
        "시도",
        "시군구",
        "코드"
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:

        raise ValueError(
            "필요한 열이 없습니다: "
            f"{missing_columns}"
        )

    # --------------------------------------------------------
    # 코드 처리
    # --------------------------------------------------------

    df["코드"] = (
        df["코드"]
        .astype(str)
        .str.strip()
    )

    df["시군구코드"] = (
        df["코드"]
        .str[:5]
    )

    # --------------------------------------------------------
    # 전체 인구 열
    # --------------------------------------------------------

    total_columns = [
        column
        for column in df.columns
        if column.startswith("계_")
    ]

    if not total_columns:

        raise ValueError(
            "'계_'로 시작하는 인구 열을 찾지 못했습니다."
        )

    # --------------------------------------------------------
    # 65세 이상 인구 열
    # --------------------------------------------------------

    elderly_columns = []

    for column in total_columns:

        age_text = column.replace(
            "계_",
            ""
        )

        if age_text == "100세 이상":

            elderly_columns.append(
                column
            )

            continue

        try:

            age = int(
                age_text.replace(
                    "세",
                    ""
                )
            )

            if age >= 65:

                elderly_columns.append(
                    column
                )

        except ValueError:

            continue

    if not elderly_columns:

        raise ValueError(
            "65세 이상 인구 열을 찾지 못했습니다."
        )

    # --------------------------------------------------------
    # 최신 연도 선택
    # --------------------------------------------------------

    latest_year = int(
        df[year_column].max()
    )

    latest = df[
        df[year_column] == latest_year
    ].copy()

    # --------------------------------------------------------
    # 인구 데이터 숫자 변환
    # --------------------------------------------------------

    for column in total_columns:

        latest[column] = pd.to_numeric(
            latest[column],
            errors="coerce"
        ).fillna(0)

    # --------------------------------------------------------
    # 시군구별 전체 인구
    # --------------------------------------------------------

    group_columns = [
        "시도",
        "시군구",
        "시군구코드"
    ]

    korea = (
        latest
        .groupby(
            group_columns,
            as_index=False
        )[total_columns]
        .sum()
    )

    korea["전체인구"] = (
        korea[total_columns]
        .sum(axis=1)
    )

    # --------------------------------------------------------
    # 시군구별 65세 이상 인구
    # --------------------------------------------------------

    elderly = (
        latest
        .groupby(
            group_columns,
            as_index=False
        )[elderly_columns]
        .sum()
    )

    elderly["65세이상인구"] = (
        elderly[elderly_columns]
        .sum(axis=1)
    )

    # --------------------------------------------------------
    # 두 데이터 합치기
    # --------------------------------------------------------

    korea = korea.merge(
        elderly[
            group_columns
            + ["65세이상인구"]
        ],
        on=group_columns,
        how="left"
    )

    # --------------------------------------------------------
    # 고령화율 계산
    # --------------------------------------------------------

    korea["고령화율"] = (
        korea["65세이상인구"]
        / korea["전체인구"]
        * 100
    )

    korea["고령화율"] = (
        korea["고령화율"]
        .replace(
            [
                float("inf"),
                -float("inf")
            ],
            0
        )
        .fillna(0)
        .round(2)
    )

    return korea, latest_year


# ============================================================
# 9. 한국 지도 만들기
# ============================================================

def make_korea_map(korea, geojson):

    def get_level(value):

        if value < 19:
            return 0

        elif value < 23:
            return 1

        elif value < 28:
            return 2

        elif value < 38:
            return 3

        else:
            return 4

    colors = [
        "#f7fbff",
        "#c6dbef",
        "#6baed6",
        "#2171b5",
        "#08306b"
    ]

    labels = [
        "19% 미만",
        "19% 이상 ~ 23% 미만",
        "23% 이상 ~ 28% 미만",
        "28% 이상 ~ 38% 미만",
        "38% 이상"
    ]

    korea = korea.copy()

    korea["등급"] = (
        korea["고령화율"]
        .apply(get_level)
    )

    fig = go.Figure()

    # GeoJSON의 코드도 문자열 5자리로 통일
    for feature in geojson.get(
        "features",
        []
    ):

        properties = feature.get(
            "properties",
            {}
        )

        if "코드" in properties:

            properties["코드"] = str(
                properties["코드"]
            ).zfill(5)

    for level in range(5):

        part = korea[
            korea["등급"] == level
        ].copy()

        if part.empty:
            continue

        target_codes = set(
            part["시군구코드"]
            .astype(str)
            .str.zfill(5)
        )

        features = []

        for feature in geojson.get(
            "features",
            []
        ):

            properties = feature.get(
                "properties",
                {}
            )

            code = str(
                properties.get(
                    "코드",
                    ""
                )
            ).zfill(5)

            if code in target_codes:

                features.append(
                    feature
                )

        level_geojson = {
            "type": "FeatureCollection",
            "features": features
        }

        customdata = part[
            [
                "시도",
                "시군구",
                "고령화율"
            ]
        ].values

        fig.add_trace(
            go.Choroplethmapbox(
                geojson=level_geojson,

                locations=part[
                    "시군구코드"
                ],

                z=[level] * len(part),

                featureidkey=(
                    "properties.코드"
                ),

                colorscale=[
                    [0, colors[level]],
                    [1, colors[level]]
                ],

                showscale=False,

                customdata=customdata,

                hovertemplate=(
                    "<b>%{customdata[1]}</b><br>"
                    "시도: %{customdata[0]}<br>"
                    "고령화율: %{customdata[2]}%"
                    "<extra></extra>"
                ),

                name=labels[level]
            )
        )

    fig.update_layout(

        mapbox=dict(
            style="white-bg",
            zoom=6,
            center=dict(
                lat=36.3,
                lon=127.8
            )
        ),

        margin=dict(
            l=0,
            r=0,
            t=60,
            b=0
        ),

        legend=dict(
            title="고령화율",
            orientation="h",
            yanchor="bottom",
            y=0.01,
            xanchor="center",
            x=0.5
        )
    )

    return fig


# ============================================================
# 10. 데이터 불러오기
# ============================================================

try:

    population_df = (
        load_population_data()
    )

    geojson_data = (
        load_geojson()
    )

    world_df, world_year = (
        load_world_data()
    )

    korea_df, korea_year = (
        make_korea_data(
            population_df
        )
    )

except Exception as e:

    st.error(
        "데이터를 불러오는 중 오류가 발생했습니다."
    )

    st.exception(e)

    st.stop()


# ============================================================
# 11. 세계 지도
# ============================================================

st.header("🌍 세계 고령화 지도")

st.caption(
    "각 국가에서 확인 가능한 가장 최근 연도의 "
    "65세 이상 인구 비율입니다."
)

world_fig = make_world_map(
    world_df
)


# ============================================================
# 12. 세계 지도 클릭 기능
# ============================================================

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


selected_iso3 = None
selected_country = None


try:

    points = (
        world_event
        .selection
        .points
    )

    if points:

        point = points[0]

        customdata = (
            point.get("customdata")
        )

        if customdata:

            selected_iso3 = (
                customdata[0]
            )

            selected_country = (
                customdata[1]
            )

except Exception:

    pass


# ============================================================
# 13. 선택한 국가의 연예인 사진
# ============================================================

if selected_iso3:

    st.subheader(
        f"🎬 {selected_country}의 연예인"
    )

    st.caption(
        "배우·가수·음악가·모델 중 "
        "Wikidata에 사진이 등록된 인물을 표시합니다."
    )

    try:

        celebrities = get_celebrities(
            selected_iso3
        )

        if celebrities:

            for start in range(
                0,
                len(celebrities),
                4
            ):

                row = celebrities[
                    start:start + 4
                ]

                columns = st.columns(
                    len(row)
                )

                for column, person in zip(
                    columns,
                    row
                ):

                    with column:

                        st.image(
                            person["image"],
                            use_container_width=True
                        )

                        st.caption(
                            person["name"]
                        )

        else:

            st.info(
                "이 국가에서 사진이 등록된 "
                "연예인 정보를 찾지 못했습니다."
            )

    except Exception as e:

        st.warning(
            "연예인 정보를 불러오지 못했습니다."
        )

        st.caption(
            f"오류 내용: {e}"
        )

else:

    st.info(
        "👆 세계 지도에서 국가를 클릭하면 "
        "해당 국가의 연예인 사진을 볼 수 있습니다."
    )


# ============================================================
# 14. 한국 시군구 지도
# ============================================================

st.divider()

st.header("🇰🇷 한국 시군구별 고령화 지도")

st.caption(
    f"{korea_year}년 기준 · 65세 이상 인구 비율"
)

korea_fig = make_korea_map(
    korea_df,
    geojson_data
)

st.plotly_chart(
    korea_fig,

    use_container_width=True,

    config={
        "displaylogo": False,
        "scrollZoom": True
    }
)


# ============================================================
# 15. 한국 시군구 순위
# ============================================================

st.subheader(
    f"📊 {korea_year}년 시군구 고령화율 순위"
)


# 고령화율 높은 지역 TOP 10
korea_top10 = (
    korea_df[
        [
            "시도",
            "시군구",
            "전체인구",
            "65세이상인구",
            "고령화율"
        ]
    ]
    .sort_values(
        "고령화율",
        ascending=False
    )
    .head(10)
    .reset_index(drop=True)
)

korea_top10.index += 1


# 고령화율 낮은 지역 TOP 10
korea_bottom10 = (
    korea_df[
        [
            "시도",
            "시군구",
            "전체인구",
            "65세이상인구",
            "고령화율"
        ]
    ]
    .sort_values(
        "고령화율",
        ascending=True
    )
    .head(10)
    .reset_index(drop=True)
)

korea_bottom10.index += 1


# ============================================================
# 16. 순위 표시
# ============================================================

left_column, right_column = (
    st.columns(2)
)


with left_column:

    st.markdown(
        "### 🔴 고령화율이 높은 지역"
    )

    st.dataframe(
        korea_top10,
        use_container_width=True
    )


with right_column:

    st.markdown(
        "### 🔵 고령화율이 낮은 지역"
    )

    st.dataframe(
        korea_bottom10,
        use_container_width=True
    )


# ============================================================
# 17. 출처
# ============================================================

st.divider()

st.caption(
    "세계 데이터: World Bank "
    "Population ages 65 and above (% of total)"
)

st.caption(
    "한국 데이터: 행정구역별 연령 인구 자료"
)

st.caption(
    "연예인 정보 및 사진: Wikidata"
)
