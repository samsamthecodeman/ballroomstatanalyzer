import React from "react";
import { router } from "expo-router";
import AccountScreen from "../../AccountScreen";
import { useAccount } from "../../accountContext";
export default function AccountRoute() {
  const a = useAccount();
  return (
    <AccountScreen
      session={a.session}
      saved={a.saved}
      ready={a.ready}
      confirmation={a.deletionConfirmation}
      preparing={a.preparingDeletion}
      onPrepareDeletion={a.prepareDeletion}
      onCancelDeletion={a.cancelDeletion}
      onUse={() => {
        a.reloadAnalysis();
        router.navigate("/");
      }}
    />
  );
}
