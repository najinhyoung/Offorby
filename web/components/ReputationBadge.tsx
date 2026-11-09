import Link from "next/link";
import type { Score } from "@/lib/types";

// 등급 색: 1~3 좋음(초록), 4~7 중간(회색), 8~10 나쁨(빨강). 라이트/다크 모두 대비 4.5:1 이상.
function gradeTone(grade: number): string {
  if (grade <= 3) return "border-green-300 bg-green-50 text-green-800 dark:border-green-800 dark:bg-green-950 dark:text-green-200";
  if (grade <= 7) return "border-gray-300 bg-gray-100 text-gray-800 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100";
  return "border-red-300 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200";
}

const LABEL = "평판등급(준비 중)";

/** 최신 점수가 있으면 "N등급 · 점수 xx.x · 표본 n건", 없으면 "데이터 부족 (표본 n건)". compact는 목록 카드용(한 줄). */
export function ReputationBadge({ score, compact = false }: { score: Score | undefined; compact?: boolean }) {
  const hasGrade = score?.grade != null && score.score != null;
  const grade = hasGrade ? (score!.grade as number) : null;

  const valueText = hasGrade
    ? `${grade}등급 · 점수 ${(score!.score as number).toFixed(1)} · 표본 ${score!.n_samples}건`
    : score
      ? `데이터 부족 (표본 ${score.n_samples}건)`
      : "데이터 부족";

  const pill = (
    <span
      className={`inline-flex shrink-0 items-center rounded border px-2 py-0.5 text-xs ${
        grade !== null ? `font-bold ${gradeTone(grade)}` : "border-dashed border-line text-muted"
      }`}
      title={`${LABEL}: ${valueText}${score ? ` (${score.snapshot_date} 기준)` : ""}`}
      aria-label={`${LABEL} ${valueText}`}
    >
      {compact && grade !== null ? `${grade}등급` : valueText}
    </span>
  );

  if (compact) return pill;

  return (
    <div className="flex shrink-0 flex-col items-end gap-1 text-right">
      <span className="text-xs text-muted">{LABEL}</span>
      {pill}
      <Link
        href="/methodology"
        className="text-xs text-accent hover:underline focus-visible:underline"
        aria-label="평판등급 산정 방법 보기"
      >
        산정 방법
      </Link>
    </div>
  );
}
