"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { Member, Score } from "@/lib/types";
import { regionOf } from "@/lib/region";
import { ReputationBadge } from "./ReputationBadge";

const ALL = "전체";
const SORTS = ["이름순", "등급순"] as const;
type Sort = (typeof SORTS)[number];

// 등급순: grade 오름차순(1이 위), NULL(데이터 부족)은 맨 뒤, 같은 등급은 score 내림차순, 그다음 이름.
function byGrade(scores: Record<string, Score>) {
  return (a: Member, b: Member) => {
    const sa = scores[a.member_code];
    const sb = scores[b.member_code];
    const ga = sa?.grade ?? Infinity;
    const gb = sb?.grade ?? Infinity;
    if (ga !== gb) return ga - gb;
    const d = (sb?.score ?? -1) - (sa?.score ?? -1);
    if (d !== 0) return d;
    return a.name.localeCompare(b.name, "ko");
  };
}

export function MemberExplorer({ members, scores = {} }: { members: Member[]; scores?: Record<string, Score> }) {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<Sort>("이름순");
  const [region, setRegion] = useState(ALL);
  const [party, setParty] = useState(ALL);
  const [type, setType] = useState("지역구");

  // 시도는 가나다순, 비례대표는 맨 뒤
  const regions = useMemo(() => {
    const set = new Set(members.map((m) => regionOf(m.district)));
    const sorted = [...set].filter((r) => r !== "비례대표").sort((a, b) => a.localeCompare(b, "ko"));
    return [ALL, ...sorted, ...(set.has("비례대표") ? ["비례대표"] : [])];
  }, [members]);
  const parties = useMemo(
    () => [ALL, ...[...new Set(members.map((m) => m.party))].sort((a, b) => a.localeCompare(b, "ko"))],
    [members],
  );

  const filtered = members.filter(
    (m) =>
      (type === ALL || m.election_type === type) &&
      (region === ALL || regionOf(m.district) === region) &&
      (party === ALL || m.party === party) &&
      (!q || m.name.includes(q) || m.district.includes(q)),
  );
  // getMembers()가 이름순으로 주므로 이름순은 원래 순서를 유지
  const sorted = sort === "등급순" ? [...filtered].sort(byGrade(scores)) : filtered;

  const select = "rounded border border-line bg-background px-2 py-2 text-sm";

  return (
    <section aria-labelledby="members-heading">
      <h2 id="members-heading" className="mb-3 text-xl font-bold">
        국회의원
      </h2>
      <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-5">
        <input
          type="search"
          placeholder="이름·지역구 검색"
          aria-label="이름 또는 지역구 검색"
          value={q}
          onChange={(e) => setQ(e.target.value.trim())}
          className={`${select} col-span-2 sm:col-span-1`}
        />
        <select aria-label="선출 구분" value={type} onChange={(e) => setType(e.target.value)} className={select}>
          {[ALL, "지역구", "비례대표"].map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
        <select aria-label="시도" value={region} onChange={(e) => setRegion(e.target.value)} className={select}>
          {regions.map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
        <select aria-label="정당" value={party} onChange={(e) => setParty(e.target.value)} className={select}>
          {parties.map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
        <select aria-label="정렬" value={sort} onChange={(e) => setSort(e.target.value as Sort)} className={select}>
          {SORTS.map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
      </div>
      <p className="mb-2 flex items-center justify-between text-sm text-muted" aria-live="polite">
        <span>{filtered.length}명</span>
        <Link href="/methodology" className="text-accent hover:underline">
          평판등급(준비 중) 산정 방법
        </Link>
      </p>
      <ul className="divide-y divide-line rounded border border-line">
        {sorted.map((m) => (
          <li key={m.member_code}>
            <Link
              href={`/members/${m.member_code}`}
              className="flex items-center justify-between gap-3 px-3 py-3 hover:bg-card"
            >
              <span className="min-w-0">
                <span className="font-medium">{m.name}</span>
                <span className="ml-2 text-sm text-muted">{m.party}</span>
                <span className="block truncate text-sm text-muted">{m.district}</span>
              </span>
              <ReputationBadge score={scores[m.member_code]} compact />
            </Link>
          </li>
        ))}
        {filtered.length === 0 && <li className="px-3 py-6 text-center text-sm text-muted">결과가 없습니다.</li>}
      </ul>
    </section>
  );
}
