import type { Metadata } from "next";
import Link from "next/link";

// docs/methodology.md(v1)를 그대로 옮긴 정적 페이지. 문장을 바꾸려면 md를 먼저 고치고 여기에 반영한다.
export const metadata: Metadata = {
  title: "평판등급(준비 중) 산정 방법 — Offorby",
  description: "Offorby 평판등급이 어떤 자료로, 어떻게 계산되는지 설명합니다.",
};

const SOURCES: [string, string, string][] = [
  ["뉴스(Google News)", "기사 제목", "50%"],
  ["유튜브", "이름으로 검색된 영상의 댓글", "30%"],
  ["커뮤니티(디시인사이드 정치 관련 갤러리)", "글 제목", "20%"],
];

const GRADES: [string, string][] = [
  ["1등급", "90~100"],
  ["2등급", "80~89"],
  ["3등급", "70~79"],
  ["4등급", "60~69"],
  ["5등급", "50~59"],
  ["6등급", "40~49"],
  ["7등급", "30~39"],
  ["8등급", "20~29"],
  ["9등급", "10~19"],
  ["10등급", "0~9"],
];

const th = "border-b border-line px-3 py-2 text-left font-medium";
const td = "border-b border-line px-3 py-2";

export default function MethodologyPage() {
  return (
    <article className="mx-auto max-w-3xl space-y-8 leading-relaxed">
      <Link href="/" className="text-sm text-accent hover:underline">
        ← 목록
      </Link>

      <header className="space-y-3">
        <h1 className="text-2xl font-bold">평판등급(준비 중) 산정 방법</h1>
        <p className="text-sm text-muted">v1</p>
        <p>
          Offorby의 평판등급은 <strong>인터넷에서 그 사람에 대해 오간 말의 분위기</strong>를 100점 점수와 10단계
          등급으로 요약한 것입니다. 사람이 손으로 매기지 않으며, 아래 절차가 매일 자동으로 돌아갑니다. 이 숫자는
          정치인의 능력이나 도덕성에 대한 평가가 아니라, 최근 온라인 여론의 방향을 보여주는 지표입니다.
        </p>
      </header>

      <section aria-labelledby="h-sources" className="space-y-3">
        <h2 id="h-sources" className="text-xl font-bold">
          1. 무엇을 보나
        </h2>
        <p>세 곳에서 그 사람의 이름이 들어간 글을 모읍니다.</p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[20rem] border-collapse text-sm">
            <thead>
              <tr>
                <th scope="col" className={th}>
                  출처
                </th>
                <th scope="col" className={th}>
                  보는 것
                </th>
                <th scope="col" className={th}>
                  비중
                </th>
              </tr>
            </thead>
            <tbody>
              {SOURCES.map(([src, what, w]) => (
                <tr key={src}>
                  <td className={td}>{src}</td>
                  <td className={td}>{what}</td>
                  <td className={td}>{w}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>글 본문이나 댓글 원문은 판정 직후 지우고 저장하지 않습니다. 남기는 것은 건수와 판정 결과뿐입니다.</p>
      </section>

      <section aria-labelledby="h-judge" className="space-y-3">
        <h2 id="h-judge" className="text-xl font-bold">
          2. 어떻게 판정하나
        </h2>
        <p>모은 글 하나하나를 AI(Claude)가 읽고 세 가지를 답합니다.</p>
        <ul className="list-disc space-y-1 pl-6">
          <li>
            이 글이 <strong>정말 그 사람 얘기인가</strong> (이름만 스쳐간 글은 제외)
          </li>
          <li>
            분위기가 <strong>긍정 / 중립 / 부정</strong> 중 무엇인가
          </li>
          <li>
            그 <strong>강도</strong>는 1(약함)~3(강함) 중 어느 정도인가
          </li>
        </ul>
        <p>출처별로 하루 최대 50건까지만 판정합니다.</p>
      </section>

      <section aria-labelledby="h-score" className="space-y-3">
        <h2 id="h-score" className="text-xl font-bold">
          3. 어떻게 점수로 만드나
        </h2>
        <ol className="list-decimal space-y-2 pl-6">
          <li>
            <strong>출처별 순감성</strong> = (긍정 − 부정) ÷ (긍정 + 중립 + 부정). 강도가 셀수록 더 크게 반영합니다.
          </li>
          <li>
            <strong>최근일수록 무겁게</strong>. 최근 28일만 보고, 14일 지날 때마다 영향이 절반으로 줄어듭니다.
          </li>
          <li>
            <strong>표본이 적으면 50점 쪽으로 당깁니다.</strong> 글이 몇 건 안 되는 사람이 우연히 극단값을 받지 않도록,
            분모에 20건 상당을 더합니다. 20건이면 원래 비율의 절반만 반영되고, 수백 건이면 거의 그대로 반영됩니다.
          </li>
          <li>출처별 순감성을 위 비중으로 합칩니다. 글이 없는 출처는 빼고 나머지 비중을 다시 100%로 맞춥니다.</li>
          <li>
            <strong>점수 = 50 + 50 × 합산 순감성</strong>. 모두 중립이면 50점, 모두 긍정이면 100점에 가까워집니다.
          </li>
        </ol>
      </section>

      <section aria-labelledby="h-grade" className="space-y-3">
        <h2 id="h-grade" className="text-xl font-bold">
          4. 등급
        </h2>
        <p>점수를 10점 단위 절대 구간으로 나눕니다. 다른 사람과의 비교가 아니라 점수 자체로 정해집니다.</p>
        <table className="w-full max-w-xs border-collapse text-sm">
          <thead>
            <tr>
              <th scope="col" className={th}>
                등급
              </th>
              <th scope="col" className={th}>
                점수
              </th>
            </tr>
          </thead>
          <tbody>
            {GRADES.map(([g, range]) => (
              <tr key={g}>
                <td className={td}>{g}</td>
                <td className={td}>{range}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p>
          28일 동안 판정된 글이 <strong>10건 미만</strong>이면 점수·등급을 내지 않고 &quot;데이터 부족&quot;으로
          표시합니다.
        </p>
      </section>

      <section aria-labelledby="h-limits" className="space-y-3">
        <h2 id="h-limits" className="text-xl font-bold">
          5. 한계
        </h2>
        <ul className="list-disc space-y-1 pl-6">
          <li>
            뉴스 제목은 정치인끼리의 공방이 많아 &quot;A가 B를 비판&quot;이라는 제목이 B의 부정으로 집계됩니다. 뉴스
            비중을 절반으로 둔 이유 중 하나입니다.
          </li>
          <li>
            유튜브 댓글은 영상 주제와 무관한 글이 많습니다. AI가 &quot;그 사람 얘기가 아님&quot;으로 걸러내지만 완벽하지
            않습니다.
          </li>
          <li>커뮤니티는 정치 관련 갤러리 네 곳만 봅니다. 특정 성향이 과대 대표될 수 있어 비중을 가장 낮게 뒀습니다.</li>
          <li>동명이인은 구분하지 못합니다.</li>
          <li>
            방법은 바뀔 수 있으며, 바뀌면 이 문서와 <code className="rounded bg-card px-1">method_version</code>을 함께
            올립니다.
          </li>
        </ul>
      </section>

      <section aria-labelledby="h-data" className="space-y-3">
        <h2 id="h-data" className="text-xl font-bold">
          6. 데이터
        </h2>
        <ul className="list-disc space-y-1 pl-6">
          <li>수집·판정 코드와 이 문서는 모두 공개 저장소에 있습니다.</li>
          <li>저장하는 것: 인물별·출처별·일별 긍정/중립/부정 건수, 점수, 등급, 뉴스 기사 제목과 링크.</li>
          <li>저장하지 않는 것: 댓글·게시글 원문, 작성자 정보.</li>
        </ul>
      </section>
    </article>
  );
}
