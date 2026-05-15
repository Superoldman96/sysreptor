<template>
  <v-list density="compact" class="match-list">
    <v-list-item
      v-for="match in visibleMatches" :key="match.field + match.from"
      :to="matchUrl(match)"
      @click="event => navigateToMatch(event, match)"
      :active="false"
    >
      <v-list-item-title>
        <span>{{ match.previewText.slice(0, match.previewFrom) }}</span>
        <span class="bg-search-match">{{ match.previewText.slice(match.previewFrom, match.previewTo) }}</span>
        <span>{{ match.previewText.slice(match.previewTo) }}</span>
      </v-list-item-title>
    </v-list-item>
    <v-list-item
      v-if="moreMatchesCount > 0"
      class="more-matches-item"
      :ripple="false"
    >
      <v-list-item-title class="text-disabled">
        {{ moreMatchesCount }} more match{{ moreMatchesCount === 1 ? '' : 'es' }}
      </v-list-item-title>
    </v-list-item>
  </v-list>
</template>

<script setup lang="ts">
const props = defineProps<{
  result: SearchResult<any>;
  toPrefix?: string;
  maxMatches?: number;
}>();

const route = useRoute();

const visibleMatches = computed(() => {
  if (!props.maxMatches || props.maxMatches < 1 || props.result.matches.length <= props.maxMatches) {
    return props.result.matches;
  }
  return props.result.matches.slice(0, props.maxMatches - 1);
});

const moreMatchesCount = computed(() => props.result.matches.length - visibleMatches.value.length);

function matchUrl(match: SearchResultMatch) {
  return props.toPrefix ? `${props.toPrefix}#${match.field}:offset=${match.from}` : undefined;
}

function navigateToMatch(event: Event, match: SearchResultMatch) {
  const path = matchUrl(match)
  if (!path) {
    return;
  }
  const url = new URL(path, window.location.href);
  if (route.path === url.pathname) {
    focusElement(url.hash, { scroll: { behavior: 'smooth', block: 'center' } });
    event.preventDefault();
  }
}

</script>

<style lang="scss" scoped>
.match-list {
  padding-top: 0;
  padding-bottom: 0;

  .v-list-item {
    padding-top: 0;
    padding-bottom: 0;
    min-height: 24px;

    .v-list-item-title {
      font-size: small;
    }
  }

  .more-matches-item {
    pointer-events: none;
  }
}
</style>
