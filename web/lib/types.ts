export type Member = {
  member_code: string;
  name: string;
  name_hanja: string | null;
  party: string;
  district: string;
  election_type: string; // 지역구 | 비례대표
  reelection: string | null;
  units: string | null;
  committees: string | null;
  tel: string | null;
  email: string | null;
  homepage: string | null;
};

// v_latest_scores 1행. person_id = members.member_code | 'PRESIDENT'. 표본 < 10이면 score·grade는 null(데이터 부족).
export type Score = {
  person_id: string;
  snapshot_date: string; // YYYY-MM-DD
  score: number | null; // 0~100
  grade: number | null; // 1(좋음)~10(나쁨)
  n_samples: number;
  n_eff: number | null;
};

export type President = {
  name: string | null; // 공석(권한대행 체제 등)이면 null
  start_date: string | null; // 취임일 YYYY-MM-DD
  verified: boolean; // 대통령실 누리집에서 이름 확인됨
};
