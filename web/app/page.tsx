import { MemberExplorer } from "@/components/MemberExplorer";
import { ReputationBadge } from "@/components/ReputationBadge";
import { getLatestScores, getMembers, getPresident, usingSampleData } from "@/lib/data";

export const revalidate = 86400; // 파이프라인이 /api/revalidate로 매일 갱신, 이건 안전망

export default async function Home() {
  const [president, members, scores] = await Promise.all([getPresident(), getMembers(), getLatestScores()]);
  // 클라이언트 컴포넌트에는 Map을 넘길 수 없어 객체로 바꾼다
  const memberScores = Object.fromEntries(scores);

  return (
    <div className="space-y-10">
      {usingSampleData && (
        <p role="note" className="rounded border border-dashed border-line bg-card px-3 py-2 text-sm text-muted">
          개발용 예시 데이터입니다. 실제 인물이 아닙니다.
        </p>
      )}

      <section aria-labelledby="president-heading">
        <h2 id="president-heading" className="mb-3 text-xl font-bold">
          대통령
        </h2>
        {president === null ? (
          <p className="rounded border border-dashed border-line px-3 py-6 text-center text-sm text-muted">
            대통령 자동 수집은 준비 중입니다.
          </p>
        ) : (
          <div className="flex items-start justify-between gap-3 rounded border border-line bg-card px-4 py-4">
            <span className="min-w-0">
              {president.name === null ? (
                <span className="text-lg font-medium text-muted">공석</span>
              ) : (
                <span className="text-lg font-medium">
                  {president.name}
                  {!president.verified && (
                    <span className="ml-1 text-xs text-muted" title="대통령실 누리집에서 아직 확인되지 않았습니다">
                      ※
                    </span>
                  )}
                </span>
              )}
              {president.start_date && <span className="block text-xs text-muted">{president.start_date} 취임</span>}
            </span>
            {president.name !== null && <ReputationBadge score={scores.get("PRESIDENT")} />}
          </div>
        )}
      </section>

      <MemberExplorer members={members} scores={memberScores} />
    </div>
  );
}
