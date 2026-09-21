@st.cache_data
def make_korea_data(df):

    df = df.copy()

    # --------------------------------------------------------
    # 1. 열 이름 정리
    # --------------------------------------------------------

    # 혹시 열 이름 앞뒤에 공백이나 BOM이 있으면 제거
    df.columns = (
        df.columns
        .astype(str)
        .str.replace("\ufeff", "", regex=False)
        .str.strip()
    )

    # --------------------------------------------------------
    # 2. 연도 열 자동 찾기
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

    # 그래도 못 찾으면 숫자형 연도처럼 보이는 열 탐색
    if year_column is None:

        for column in df.columns:

            try:
                values = pd.to_numeric(
                    df[column],
                    errors="coerce"
                )

                valid_values = values.dropna()

                if len(valid_values) > 0:

                    # 2000~2100 사이 값이 충분히 있으면 연도 열로 판단
                    year_ratio = (
                        valid_values.between(
                            2000,
                            2100
                        ).mean()
                    )

                    if year_ratio > 0.8:
                        year_column = column
                        break

            except Exception:
                continue

    if year_column is None:

        st.error(
            "인구 데이터에서 연도 열을 찾지 못했습니다."
        )

        st.write(
            "현재 CSV의 열 이름:"
        )

        st.write(
            list(df.columns)
        )

        st.stop()

    # 연도 숫자 변환
    df[year_column] = pd.to_numeric(
        df[year_column],
        errors="coerce"
    )

    df = df.dropna(
        subset=[year_column]
    )

    # --------------------------------------------------------
    # 3. 코드 열 확인
    # --------------------------------------------------------

    if "코드" not in df.columns:

        st.error(
            "인구 데이터에 '코드' 열이 없습니다."
        )

        st.write(
            "현재 CSV의 열 이름:"
        )

        st.write(
            list(df.columns)
        )

        st.stop()

    # 코드 앞뒤 공백 제거
    df["코드"] = (
        df["코드"]
        .astype(str)
        .str.strip()
    )

    # 시군구 코드 = 읍면동 코드 앞 5자리
    df["시군구코드"] = (
        df["코드"]
        .str[:5]
    )

    # --------------------------------------------------------
    # 4. 전체 인구 컬럼 찾기
    # --------------------------------------------------------

    total_columns = [
        column
        for column in df.columns
        if column.startswith("계_")
    ]

    if not total_columns:

        st.error(
            "'계_'로 시작하는 인구 데이터 열을 찾지 못했습니다."
        )

        st.write(
            "현재 CSV의 열 이름:"
        )

        st.write(
            list(df.columns)
        )

        st.stop()

    # --------------------------------------------------------
    # 5. 65세 이상 인구 컬럼 찾기
    # --------------------------------------------------------

    elderly_columns = []

    for column in total_columns:

        age_text = column.replace(
            "계_",
            ""
        )

        # 65세 ~ 100세 이상
        if age_text == "100세 이상":

            elderly_columns.append(
                column
            )

        else:

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

        st.error(
            "65세 이상 인구 데이터를 찾지 못했습니다."
        )

        st.stop()

    # --------------------------------------------------------
    # 6. 최신 연도 데이터 선택
    # --------------------------------------------------------

    latest_year = int(
        df[year_column].max()
    )

    latest = df[
        df[year_column] == latest_year
    ].copy()

    # --------------------------------------------------------
    # 7. 인구 열을 숫자로 변환
    # --------------------------------------------------------

    for column in total_columns:

        latest[column] = pd.to_numeric(
            latest[column],
            errors="coerce"
        ).fillna(0)

    # --------------------------------------------------------
    # 8. 시군구 단위로 합산
    # --------------------------------------------------------

    group_columns = [
        "시도",
        "시군구",
        "시군구코드"
    ]

    # 필요한 지역 정보가 없는 경우 확인
    missing_group_columns = [
        column
        for column in group_columns
        if column not in latest.columns
    ]

    if missing_group_columns:

        st.error(
            "지역 구분에 필요한 열이 없습니다."
        )

        st.write(
            "없는 열:",
            missing_group_columns
        )

        st.write(
            "현재 CSV의 열 이름:",
            list(latest.columns)
        )

        st.stop()

    korea = (
        latest
        .groupby(
            group_columns,
            as_index=False
        )[total_columns]
        .sum()
    )

    # --------------------------------------------------------
    # 9. 전체 인구 계산
    # --------------------------------------------------------

    korea["전체인구"] = (
        korea[total_columns]
        .sum(axis=1)
    )

    # --------------------------------------------------------
    # 10. 65세 이상 인구 계산
    # --------------------------------------------------------

    # 65세 이상 컬럼만 따로 집계
    elderly_sum = (
        latest
        .groupby(
            group_columns,
            as_index=False
        )[elderly_columns]
        .sum()
    )

    elderly_sum["65세이상인구"] = (
        elderly_sum[elderly_columns]
        .sum(axis=1)
    )

    # 전체 인구 데이터와 합치기
    korea = korea.merge(
        elderly_sum[
            group_columns + [
                "65세이상인구"
            ]
        ],
        on=group_columns,
        how="left"
    )

    # --------------------------------------------------------
    # 11. 고령화율 계산
    # --------------------------------------------------------

    korea["고령화율"] = (
        korea["65세이상인구"]
        / korea["전체인구"]
        * 100
    )

    korea["고령화율"] = (
        korea["고령화율"]
        .replace(
            [float("inf"), -float("inf")],
            0
        )
        .fillna(0)
        .round(2)
    )

    return korea, latest_year
