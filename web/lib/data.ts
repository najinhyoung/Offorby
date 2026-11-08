import "server-only";
import { BigQuery } from "@google-cloud/bigquery";
import type { Member, President } from "./types";
import { sampleMembers, samplePresident } from "./sample";

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
