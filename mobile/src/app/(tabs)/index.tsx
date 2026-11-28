import React from "react";
import AnalysisScreen from "../../AnalysisScreen";
import { useAccount } from "../../accountContext";
export default function AnalyzeRoute() {
  const a = useAccount();
  return (
    <AnalysisScreen
      key={a.analysisKey}
      saved={a.saved}
      signedIn={!!a.session}
      onSave={a.save}
    />
  );
}
