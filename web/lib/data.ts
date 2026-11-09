import "server-only";
import { BigQuery } from "@google-cloud/bigquery";
import type { Member, President, Score } from "./types";
import { sampleMembers, samplePresident, sampleScores } from "./sample";

// GCP_PROJECT / GCP_SA_KEY(서비스계정 JSON 문자열)가 없으면 로컬 개발용 가짜 데이터를 쓴다.
const project = process.env.GCP_PROJECT;
const dataset = process.env.BQ_DATASET ?? "offorby";

export const usingSampleData = !project;

let client: BigQuery | null = null;
function bq(): BigQuery {
  if (!client) {
    const key = process.env.GCP_SA_KEY;
    client = new BigQuery({ projectId: project, ...(key ? { credentials: JSON.parse(key) } : {}) });
  }
  return client;
}

async function query<T>(sql: string, params: Record<string, unknown> = {}): Promise<T[]> {
  const [rows] = await bq().query({ query: sql, params, location: "asia-northeast3" });
  return rows as T[];
}

export async function getMembers(): Promise<Member[]> {
  if (usingSampleData) return sampleMembers;
  return query<Member>(`SELECT * EXCEPT (valid_from) FROM \`${project}.${dataset}.v_current_members\` ORDER BY name`);
}

export async function getMember(code: string): Promise<Member | null> {
  if (usingSampleData) return sampleMembers.find((m) => m.member_code === code) ?? null;
  const rows = await query<Member>(
    `SELECT * EXCEPT (valid_from) FROM \`${project}.${dataset}.v_current_members\` WHERE member_code = @code`,
    { code },
  );
  return rows[0] ?? null;
}

export async function getPresident(): Promise<President | null> {
  if (usingSampleData) return samplePresident;
  const rows = await query<Omit<President, "start_date"> & { start_date: { value: string } | string | null }>(
    `SELECT name, start_date, verified FROM \`${project}.${dataset}.v_current_president\` LIMIT 1`,
  );
  const r = rows[0];
  if (!r) return null;
  // BigQuery DATE는 {value: "YYYY-MM-DD"} 객체로 온다
  return {
    name: r.name,
    start_date: r.start_date && typeof r.start_date === "object" ? r.start_date.value : r.start_date,
    verified: Boolean(r.verified),
  };
}

// 평판등급(준비 중). person_id → 최신 점수. 뷰가 없거나 조회에 실패하면 빈 Map(화면은 "데이터 부족"으로 표시).
type ScoreRow = Omit<Score, "snapshot_date"> & { snapshot_date: { value: string } | string | null };

export async function getLatestScores(): Promise<Map<string, Score>> {
  const rows: Score[] = usingSampleData ? sampleScores : await queryScores();
  return new Map(rows.map((s) => [s.person_id, s]));
}

async function queryScores(): Promise<Score[]> {
  try {
    const rows = await query<ScoreRow>(
      `SELECT person_id, snapshot_date, score, grade, n_samples, n_eff FROM \`${project}.${dataset}.v_latest_scores\``,
    );
    return rows.map((r) => ({
      person_id: r.person_id,
      // BigQuery DATE는 {value: "YYYY-MM-DD"} 객체로 온다
      snapshot_date: r.snapshot_date && typeof r.snapshot_date === "object" ? r.snapshot_date.value : (r.snapshot_date ?? ""),
      score: r.score === null ? null : Number(r.score),
      grade: r.grade === null ? null : Number(r.grade),
      n_samples: Number(r.n_samples),
      n_eff: r.n_eff === null ? null : Number(r.n_eff),
    }));
  } catch (e) {
    console.warn("v_latest_scores 조회 실패(뷰 미생성 또는 권한). 점수 없이 렌더합니다.", e);
    return [];
  }
}
