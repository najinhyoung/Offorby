import type { Member, President, Score } from "./types";

// 로컬 개발용 가짜 데이터. 실존 인물·정당이 아님.
const districts = [
  "서울 종로구", "서울 강남구갑", "부산 해운대구갑", "대구 수성구을", "인천 연수구갑",
  "광주 북구갑", "대전 유성구을", "울산 남구갑", "세종특별자치시갑", "경기 수원시갑",
  "경기 성남시분당구을", "강원 춘천시철원군화천군양구군갑", "충북 청주시상당구", "충남 천안시갑",
  "전북 전주시갑", "전남 목포시", "경북 포항시북구", "경남 창원시성산구", "제주 제주시갑",
];
const parties = ["가나당", "다라당", "마바당", "무소속"];

export const sampleMembers: Member[] = Array.from({ length: 30 }, (_, i) => {
  const proportional = i >= districts.length;
  return {
    member_code: `SAMPLE${String(i + 1).padStart(3, "0")}`,
    name: `예시의원${String(i + 1).padStart(2, "0")}`,
    name_hanja: null,
    party: parties[i % parties.length],
    district: proportional ? "비례대표" : districts[i],
    election_type: proportional ? "비례대표" : "지역구",
    reelection: ["초선", "재선", "3선"][i % 3],
    units: "제22대",
    committees: ["법제사법위원회", "기획재정위원회", "교육위원회"][i % 3],
    tel: null,
    email: null,
    homepage: null,
  };
});

export const samplePresident: President = { name: "예시대통령", start_date: "2025-06-04", verified: false };

// 평판등급(준비 중) 폴백. 등급 구간·데이터 부족 케이스가 한 화면에 보이도록 섞어 둔다.
const sampleScoreRows: [string, number | null, number | null, number, number | null][] = [
  ["PRESIDENT", 63.4, 4, 212, 148.2],
  ["SAMPLE001", 91.2, 1, 48, 31.5],
  ["SAMPLE002", 74.8, 3, 35, 22.1],
  ["SAMPLE003", 52.0, 5, 120, 80.6],
  ["SAMPLE004", 44.5, 6, 27, 18.3],
  ["SAMPLE005", 23.7, 8, 64, 40.9],
  ["SAMPLE006", 8.1, 10, 19, 12.4],
  ["SAMPLE007", null, null, 6, 4.2], // 표본 부족
  ["SAMPLE008", 50.0, 5, 10, 7.0],
];
export const sampleScores: Score[] = sampleScoreRows.map(([person_id, score, grade, n_samples, n_eff]) => ({
  person_id,
  snapshot_date: "2026-11-09",
  score,
  grade,
  n_samples,
  n_eff,
}));
