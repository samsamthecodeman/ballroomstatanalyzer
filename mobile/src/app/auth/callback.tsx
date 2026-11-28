import React, { useEffect } from "react";
import { View } from "react-native";
import { router } from "expo-router";
import { useAccount } from "../../accountContext";
import { Button, Heading, Note, s } from "../../ui";
export default function Callback() {
  const account = useAccount();
  useEffect(() => {
    if (account.session) router.replace("/");
  }, [account.session]);
  return (
    <View style={s.screen}>
      <Heading title="Welcome back." />
      <Note>
        Finishing sign-in. You can return to the app if the provider cancelled
        your request.
      </Note>
      <Button title="Return to app" onPress={() => router.replace("/")} />
    </View>
  );
}
