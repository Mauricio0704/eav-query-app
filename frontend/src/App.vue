<script setup>
import { onMounted } from 'vue'
import { init, state } from './store.js'
import Sidebar from './components/Sidebar.vue'
import TopBar from './components/TopBar.vue'
import ResultsPanel from './components/ResultsPanel.vue'
import ChatPanel from './components/ChatPanel.vue'

onMounted(init)
</script>

<template>
  <div
    class="flex h-screen overflow-hidden"
    style="
      background: linear-gradient(
        90deg,
        rgb(248, 250, 252) 0%,
        rgb(248, 250, 252) 100%
      );
    "
  >
    <Sidebar />
    <main class="flex-1 flex flex-col overflow-hidden">
      <TopBar />
      <ChatPanel v-if="state.queryMode === 'ai'" />
      <ResultsPanel v-else />
    </main>
  </div>
</template>
