<template>
  <!--
    Gescrollt wird in <main>, nicht im Dokument.

    Die Huelle ist genau einen Bildschirm hoch, also bleiben Kopfzeile und
    Navigation stehen, wo sie sind — ohne `position: fixed`, ohne die Hoehe
    der Kopfzeile irgendwo als Zahl zu wiederholen und ohne dass die
    Navigation eine eigene Bildlaufleiste ins Nichts bekommt.

    `h-full` und nicht `h-dvh`: die Hoehe kommt jetzt ueber `html, body {
    height: 100% }` aus dem Dokument statt aus einer Viewport-Einheit. Der
    Unterschied ist genau ein Scrollbalken. Viewport-Einheiten messen den
    Bildschirm *einschliesslich* eines waagerechten Scrollbalkens — taucht
    einer auf, ist die Huelle um dessen Hoehe zu hoch, das Dokument bekommt
    einen senkrechten Scrollbalken dazu, der nimmt Breite weg, und die
    naechste Zeile passt erst recht nicht mehr. Ein Prozentwert kann das
    nicht: er ist die Hoehe, die wirklich da ist. Der Grund fuer `dvh` faellt
    damit nicht weg, er wird nur anders erfuellt — `height: 100%` loest
    gegen den kleinen Viewport auf und laeuft mit ausgefahrener Adressleiste
    ebenso wenig ueber.

    Vorher scrollte das Dokument, und die Navigation lief bei einer langen
    Liste (Mailversand, Telefonakquise) nach oben aus dem Bild. Das
    `sticky top-0` der Kopfzeile hat damit nichts mehr zu halten, bleibt aber
    stehen: es haelt ihren Stapelkontext (`z-40`) ueber dem Inhalt und traegt
    den Fall, dass hier wieder das Dokument scrollt.
  -->
  <!-- `app-shell` ist keine Gestaltung, sondern die Marke, an der
       `style.css` das Dokument stilllegt: nur wo diese Huelle steht, darf
       ausschliesslich <main> scrollen (die Anmeldeseite hat kein Dashboard
       und scrollt weiter wie jede Seite). -->
  <div class="app-shell flex h-full flex-col">
    <!-- Topbar -->
    <!-- shrink-0: in einer Spalte darf ein Flex-Element unter seinen Inhalt
         schrumpfen — ohne das quetscht eine hohe Seite die Kopfzeile. -->
    <TopBar class="shrink-0" />

    <!-- Body -->
    <!-- light-grey-background: liegt hinter <main>, damit dessen
         abgerundete obere linke Ecke die Nav-Farbe durchscheinen laesst.
         min-h-0: dieselbe Regel wie `min-w-0` eine Zeile tiefer, nur fuer die
         Hoehe — ohne das waere diese Zeile so hoch wie ihr Inhalt und
         schoebe die Kopfzeile aus dem Bild, statt <main> scrollen zu
         lassen. -->
    <div class="flex min-h-0 flex-1 overflow-hidden light-grey-background">
      <!-- Sidebar -->
      <Sidebar />

      <!-- Main Content -->
      <!-- min-w-0: ohne das kann <main> nicht schmaler werden als sein
           Inhalt, und eine breite Seite (Kanban-Board) schiebt Sidebar und
           Topbar aus dem Bild statt selbst zu scrollen. -->
      <main class="min-w-0 flex-1 overflow-y-auto content-area grey-background">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import TopBar from "../components/topbar/TopBar.vue";
import Sidebar from "../components/sidebar/SideBar.vue";
</script>
