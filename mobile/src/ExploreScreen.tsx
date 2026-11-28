import React, { useState } from "react";
import { Linking, Platform, View } from "react-native";
import { WebView } from "react-native-webview";
import { API_URL } from "./api";
import { Button, Heading, Note, s, usePalette } from "./ui";
export default function ExploreScreen() {
  const c = usePalette(),
    [failed, setFailed] = useState(false),
    [reload, setReload] = useState(0);
  if (Platform.OS === "web")
    return (
      <View style={s.screen}>
        <Heading
          title="Go deeper."
          subtitle="Comparisons, YCN points, upcoming schedules, and exports are available on the full dashboard."
        />
        <Button
          title="Open full dashboard"
          onPress={() => Linking.openURL(API_URL)}
        />
      </View>
    );
  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      <View style={{ paddingHorizontal: 20 }}>
        <Note>
          Full dashboard · comparisons, proficiency points, schedules, and
          exports.
        </Note>
      </View>
      {failed ? (
        <View style={s.screen}>
          <Note error>
            The dashboard could not load. Check your connection and try again.
          </Note>
          <Button
            title="Retry"
            onPress={() => {
              setFailed(false);
              setReload(reload + 1);
            }}
          />
        </View>
      ) : (
        <WebView
          key={reload}
          source={{ uri: API_URL }}
          startInLoadingState
          sharedCookiesEnabled={false}
          thirdPartyCookiesEnabled={false}
          onError={() => setFailed(true)}
          onHttpError={() => setFailed(true)}
          setSupportMultipleWindows={false}
          allowsBackForwardNavigationGestures
          onShouldStartLoadWithRequest={(request) => {
            try {
              if (
                new URL(request.url).origin === new URL(API_URL).origin ||
                request.url === "about:blank"
              )
                return true;
            } catch {
              return false;
            }
            if (/^https:\/\//.test(request.url))
              Linking.openURL(request.url).catch(() => {});
            return false;
          }}
        />
      )}
      <View style={{ padding: 12 }}>
        <Button
          title="Open in browser for CSV / PDF downloads"
          quiet
          onPress={() => Linking.openURL(API_URL)}
        />
      </View>
    </View>
  );
}
