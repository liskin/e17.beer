Jekyll::Hooks.register :site, :after_init do |site|
  site.config['places_json_last_update'] = `git -C "#{site.source}" log -1 --format="%cs" -- _data/places.json`.strip
end
