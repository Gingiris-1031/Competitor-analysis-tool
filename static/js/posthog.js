// PostHog client-side analytics (pageviews, sessions, clicks).
// The project API key (phc_...) is public by design — it can only *send*
// events, never read data. Never put a personal API key (phx_...) here.
!function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="init capture register register_once register_for_session unregister unregister_for_session getFeatureFlag getFeatureFlagPayload isFeatureEnabled reloadFeatureFlags updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures on onFeatureFlags onSessionId getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey identify setPersonProperties group resetGroups setPersonPropertiesForFlags resetPersonPropertiesForFlags setGroupPropertiesForFlags resetGroupPropertiesForFlags reset getProperty getGroupPropertiesForFlags".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
posthog.init("phc_syZTd93YA3LxUjLRhyQAKkDpvrUoEC88vXDk8ckymQg3",{
  api_host:"https://us.i.posthog.com",
  // Start with safe, high-signal product analytics.  We deliberately leave
  // click autocapture and session recording off until a reviewed event plan is
  // in place, so report contents, URLs typed into forms, and account data are
  // never collected incidentally.
  autocapture:false,
  disable_session_recording:true,
  mask_all_text:true,
  mask_all_element_attributes:true,
  before_send:function(event){
    // Strip query strings/fragments from automatic page events.  Auth and
    // payment return links may carry short-lived or otherwise sensitive data.
    try {
      var url=event&&event.properties&&event.properties.$current_url;
      if(url){var parsed=new URL(url);parsed.search="";parsed.hash="";event.properties.$current_url=parsed.toString()}
    } catch (_) {}
    return event;
  }
})
