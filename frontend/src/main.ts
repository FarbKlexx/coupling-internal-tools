import { createApp } from "vue";
import App from "./App.vue";
import "./style.css";
import { router } from "./router";
import { vuetify } from "./plugins/vuetify";
import { setUnauthorizedHandler } from "./api/http";
import { useAuth } from "./composables/useAuth";

/**
 * Was bei einem 401 aus einem beliebigen Request passiert.
 *
 * Hier verdrahtet und nicht in `http.ts`, weil Router und Auth-Composable
 * ihrerseits Module laden, die `http` brauchen — der Zirkel ergäbe eine halb
 * initialisierte Axios-Instanz.
 *
 * `replace` statt `push`: eine abgelaufene Sitzung soll keinen Eintrag in der
 * Verlaufsliste hinterlassen, über den man wieder in die tote Seite zurück
 * navigiert.
 */
setUnauthorizedHandler(() => {
  const auth = useAuth();
  auth.forget();

  if (router.currentRoute.value.name !== "login") {
    void router.replace({
      name: "login",
      query: { weiter: router.currentRoute.value.fullPath },
    });
  }
});

createApp(App).use(router).use(vuetify).mount("#app");
