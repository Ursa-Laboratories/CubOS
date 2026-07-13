import { useQuery } from "@tanstack/react-query";
import { dataApi } from "../api/client";

export function useExperimentData() {
  return useQuery({
    queryKey: ["data", "campaigns"],
    queryFn: dataApi.listCampaigns,
  });
}
