import Link from "next/link";
import { notFound } from "next/navigation";
import { ReputationBadge } from "@/components/ReputationBadge";
import { getLatestScores, getMember } from "@/lib/data";

export const revalidate = 86400;

// 빌드 시엔 만들지 않고 첫 방문 때 생성 후 캐시(ISR)
export async function generateStaticParams() {
  return [];
}

export default async function MemberPage({ params }: { params: Promise<{ code: string }> }) {
  const { code } = await params;
  const [m, scores] = await Promise.all([getMember(code), getLatestScores()]);
  if (!m) notFound();
  const score = scores.get(m.member_code);

  const rows: [string, string | null][] = [
    ["정당", m.party],
    ["선거구", m.district],
    ["선출 구분", m.election_type],
    ["당선 횟수", m.reelection],
    ["소속 위원회", m.committees],
    ["전화", m.tel],
    ["이메일", m.email],
  ];

  return (
    <article className="space-y-6">
      <Link href="/" className="text-sm text-accent hover:underline">
        ← 목록
      </Link>
      <header className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">
            {m.name}
            {m.name_hanja && <span className="ml-2 text-base font-normal text-muted">{m.name_hanja}</span>}
          </h1>
          <p className="text-muted">
            {m.party} · {m.district}
          </p>
        </div>
        <ReputationBadge score={score} />
      </header>
      <dl className="divide-y divide-line rounded border border-line">
        {rows
          .filter(([, v]) => v)
          .map(([k, v]) => (
            <div key={k} className="grid grid-cols-[7rem_1fr] gap-3 px-3 py-2 text-sm">
              <dt className="text-muted">{k}</dt>
              <dd className="break-words">{v}</dd>
            </div>
          ))}
      </dl>
      {m.homepage && (
        <a href={m.homepage} target="_blank" rel="noopener noreferrer" className="text-sm text-accent hover:underline">
          홈페이지 ↗
        </a>
      )}
      <section className="rounded border border-dashed border-line px-3 py-6 text-center text-sm text-muted">
        {score
          ? `평판등급(준비 중)은 ${score.snapshot_date} 기준 최근 28일 온라인 언급을 집계한 값입니다. 한줄평은 준비 중입니다.`
          : "인터넷 언급량·뉴스 평판과 한줄평은 준비 중입니다."}
      </section>
    </article>
  );
}
