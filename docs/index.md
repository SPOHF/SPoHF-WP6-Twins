# Welcome

To the home of WP6 - Digital twin. A workpackage within
[SPoHF (Sustainable Production of Healthy Food)](https://www.spohf.com/).

![SPoHF](./assets/spohf.png)
*image generated with chatGPT*


![Interreg](./assets/interreg.png)

The project contains two twins that are based on studies from other work packages:
- the `Blue` domain represents blueberries (at Compass Agro (NL))
- the `Red` domain represents tomatoes in a greenhouse  (at Vitarom (DE))

### Dashboards

| Dashboard | Status | Reason/remark | Data source | Auth | URL |
|-----------|--------| -------|---------|------|-----|
| **Blue** |🔴 Usage discouraged | Data source not ready | Synced from SPoHF API (AppComm) | Public | [wp6-blue.spohf.fontysvenlo.dev](https://wp6-blue.spohf.fontysvenlo.dev) |
| **Red** | 🟢 Ready for use | Temporary data source (data from october 2025) | Fontys GreenTechLab database | Basic Auth | [wp6-red.spohf.fontysvenlo.dev](https://wp6-red.spohf.fontysvenlo.dev) |

## Two twins

There are two sets of digital twins.
On a high level, they share:
- similar design
  - so that parts (code, infrastructre) can be reused
- data formats
- basic dashboarding, showing data over time.

In behavior they are different, due to different data, models and usage.
Hence, the Blue Twin and a Red Twin, named after the color of the fruits.

For both, this is the direction we're heading into.

### Blue Twin

The blue(berry) twin approach is as following:
Different fertilization strategies are used in a field where other variables (e.g. irrigation) are kept the same. from where chemical analysis shows which one works the best.
This of course is a slow feedback cycle.

Based on which works the best, the goal of the twin is to find the correlations in the sensor data with the best fertilization strategy, to see if there is a faster feedback cycle from the sensors.

This ultimately helps prescribing actions to take over the year to get a more desirable harvest.

these actions include: irrigation, adding nutrients, pest control

### Red Twin

The red twin (tomato) is as following:
As tomatoes grow in greenhouses, the climate is controlled at large scale.

A setup is being made for measuring at different heights:
- light (PAR)
- temperature
- humidity
- fruit thickness

From here we can visualize and model the microclimate around a single plant and its growth.

This ultimately prescribe actions that lead to reduced costs without impacting the harvest.

these actions may include: leaf maintenance, heat control, light control and positioning and water control.



## Architecture

see [architecture](architecture/index.md)

## Code repository

github [SPoHF-WP6-Twins repository](https://github.com/SPoHF/SPoHF-WP6-Twins/)
